#!/usr/bin/env python3
"""Prove the credential overlap is real, and that the consumer's obligation is not prose (§13 bound 6).

PostgreSQL stores one verifier per role, so two valid passwords for a single role cannot exist.
That is why §11.4 originally promised no overlap, and why "none" left the requirement owed. The
remedy §13 names is a login-role PAIR sharing a non-login privilege role, so the structural
assertions here are the load-bearing ones: two login roles, granted into an owner role that cannot
log in, each with its OWN Secret.

The failure this is really guarding against is subtle and total: point both login roles at the same
`passwordSecret` and every field in `status.credentials` still looks right, while the overlap is
gone — rotating one rotates both. `both-slots-share-a-secret` below is that case.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

TESTS_DIR = Path(__file__).resolve().parent
CAPABILITY_DIR = TESTS_DIR.parent.parent
COMPOSITION_PATH = CAPABILITY_DIR / "crossplane/composition.yaml"
XRD_PATH = CAPABILITY_DIR / "crossplane/xrd.yaml"

RFC3339 = "%Y-%m-%dT%H:%M:%SZ"
DURATION = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")
OWNER_ROLE = "app"
LOGIN_ROLES = ("app_a", "app_b")


class OverlapError(ValueError):
    pass


def parse_duration(value: str, field: str) -> int:
    match = DURATION.match(value or "")
    if not match or not any(match.groups()):
        raise OverlapError(f"{field} is not an accepted ISO-8601 duration: {value!r}")
    hours, minutes, seconds = (int(g or 0) for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def composition_source() -> str:
    return COMPOSITION_PATH.read_text()


def declared_windows() -> tuple[int, int]:
    """(production, development) overlap seconds, read from Composition SOURCE."""
    source = composition_source()
    window = re.findall(
        r'\{\{- \$credentialOverlapWindow := ternary "([A-Z0-9]+)" "([A-Z0-9]+)" \$isProduction \}\}',
        source,
    )
    seconds = re.findall(
        r"\{\{- \$credentialOverlapSeconds := ternary (\d+) (\d+) \$isProduction \}\}", source
    )
    if len(window) != 1 or len(seconds) != 1:
        raise OverlapError(
            "Composition must declare exactly one $credentialOverlapWindow and one "
            f"$credentialOverlapSeconds; found {len(window)} and {len(seconds)}"
        )
    prod_window, dev_window = (parse_duration(v, "overlapWindow") for v in window[0])
    prod_seconds, dev_seconds = (int(v) for v in seconds[0])
    # The ISO string is what consumers read; the integer is what the arithmetic uses. If they ever
    # disagree, status advertises a window the platform does not actually honour.
    if (prod_window, dev_window) != (prod_seconds, dev_seconds):
        raise OverlapError(
            f"declared window strings {window[0]} disagree with the arithmetic {seconds[0]}: "
            "status would advertise a window the platform does not honour"
        )
    return prod_seconds, dev_seconds


def role_definitions(source: str | None = None) -> list[dict[str, Any]]:
    """Parse the composed CNPG managed roles out of the template.

    The template is not loadable YAML, so the roles block is extracted textually and then parsed.
    Reading the composed SPEC rather than a rendered output is deliberate here: this asserts what
    the platform always composes, not what one fixture happened to produce.
    """
    text = source if source is not None else composition_source()
    match = re.search(r"\n(\s+)roles:\n(.*?)\n\s+storage:", text, re.DOTALL)
    if not match:
        raise OverlapError("could not locate the managed `roles:` block in the Composition")
    indent, body = match.group(1), match.group(2)
    lines = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("{{"):
            continue
        # Resolve the two template forms that appear inside the roles block.
        line = re.sub(r'\{\{ printf "app_%s" "([ab])" \| quote \}\}', r'"app_\1"', line)
        line = re.sub(r"\{\{ \$ownerRole \| quote \}\}", f'"{OWNER_ROLE}"', line)
        line = re.sub(
            r'\{\{ printf "%s-([ab])" \$spec\.credentialsSecretRef\.name \| quote \}\}',
            r'"BASE-\1"',
            line,
        )
        if "{{" in line:
            raise OverlapError(f"unresolved template in the roles block: {line.strip()!r}")
        lines.append(line[len(indent) :])
    roles = yaml.safe_load("\n".join(lines))
    if not isinstance(roles, list):
        raise OverlapError("the roles block did not parse to a list")
    return roles


def check_role_structure(source: str | None = None) -> None:
    roles = role_definitions(source)
    by_name = {r["name"]: r for r in roles}

    owner = by_name.get(OWNER_ROLE)
    if owner is None:
        raise OverlapError(f"no {OWNER_ROLE!r} owner role is composed")
    if owner.get("login") is not False:
        raise OverlapError(
            f"{OWNER_ROLE!r} owns the data and MUST be NOLOGIN: a login owner role means the "
            "shared privileges are reachable with a credential that never rotates"
        )
    if "passwordSecret" in owner:
        raise OverlapError(f"{OWNER_ROLE!r} must have no password: it is not a login role")

    secrets = {}
    for name in LOGIN_ROLES:
        role = by_name.get(name)
        if role is None:
            raise OverlapError(f"login role {name!r} is not composed; there is no pair to rotate")
        if role.get("login") is not True:
            raise OverlapError(f"{name!r} must be a login role")
        if role.get("inRoles") != [OWNER_ROLE]:
            raise OverlapError(
                f"{name!r} must be granted into {OWNER_ROLE!r} only, got {role.get('inRoles')!r}: "
                "grants held directly by a login role cannot survive its rotation"
            )
        secret = (role.get("passwordSecret") or {}).get("name")
        if not secret:
            raise OverlapError(f"{name!r} has no passwordSecret")
        secrets[name] = secret

    if len(set(secrets.values())) != len(LOGIN_ROLES):
        raise OverlapError(
            f"the login roles share a passwordSecret ({secrets}): rotating one rotates both, so "
            "there is no overlap at all — the status fields would still look correct"
        )
    print(
        f"PASS role structure: {OWNER_ROLE} NOLOGIN owns the data; "
        f"{', '.join(f'{k}->{v}' for k, v in secrets.items())} are distinct login credentials"
    )


def check_declared_windows() -> None:
    production, development = declared_windows()
    if production <= 0 or development <= 0:
        raise OverlapError(
            f"an overlap window of zero is the absence of overlap "
            f"(production={production}s, development={development}s)"
        )
    if production >= development:
        raise OverlapError(
            f"production overlap ({production}s) must be SHORTER than development "
            f"({development}s): a previous credential that still authenticates is standing "
            "exposure, and production is where that matters most"
        )
    print(
        f"PASS declared windows: production={production}s < development={development}s, both > 0"
    )


def check_xrd() -> None:
    xrd = yaml.safe_load(XRD_PATH.read_text())
    schema = xrd["spec"]["versions"][0]["schema"]["openAPIV3Schema"]
    credentials = schema["properties"]["status"]["properties"]["credentials"]["properties"]
    for field in (
        "activeRole",
        "previousRole",
        "overlapWindow",
        "previousCredentialAccepted",
        "previousCredentialRevoked",
        "previousValidUntil",
    ):
        if field not in credentials:
            raise OverlapError(f"status.credentials.{field} is missing from the XRD")
    for field in ("previousCredentialAccepted", "previousCredentialRevoked"):
        if credentials[field].get("type") != "boolean":
            raise OverlapError(f"{field} must be a boolean, not a description")
    for field in ("activeRole", "previousRole"):
        if credentials[field].get("pattern") != "^app_[ab]$":
            raise OverlapError(f"{field} must be constrained to the composed login-role pair")
    print("PASS XRD schema: overlap and proven revocation are published as machine-readable booleans")


def check_rotation_source(source: str | None = None) -> None:
    """Pin the remote-RV/CNPG proof; deadline time alone is not revocation."""
    text = source if source is not None else composition_source()
    required = (
        '$activeSlot := dig "platform.openkubes.ai/active-credential-slot" "a" $xrAnnotations',
        '$previousStartVersion := dig "platform.openkubes.ai/previous-credential-resource-version" "" $xrAnnotations',
        '$previousStartDigest := dig "platform.openkubes.ai/previous-credential-digest" "" $xrAnnotations',
        '$previousPasswordDigest = sha256sum $previousPasswordBase64',
        '$previousCredentialApplied := and $previousCredentialReconciled (ne $previousPublishedVersion "") (eq $previousPublishedVersion $previousAppliedVersion)',
        '$previousStartCredentialApplied := and $previousCredentialReconciled (eq $previousAppliedVersion $previousStartVersion)',
        '$previousPasswordReplaced := and (ne $previousPasswordDigest "") (ne $previousPasswordDigest $previousStartDigest)',
        '$previousCredentialRevoked := and $rotationStarted $previousCredentialApplied $previousPasswordReplaced',
        '$previousCredentialAccepted := and $rotationStarted (or $previousCredentialApplied $previousStartCredentialApplied) (not $previousCredentialRevoked)',
        '$previousCredentialAcceptanceKnown := or (not $rotationAnnotationsPresent) $previousCredentialAccepted $previousCredentialRevoked',
        '{{- if $previousCredentialAcceptanceKnown }}',
        'name: {{ printf "%s-%s" $spec.credentialsSecretRef.name $slot | quote }}',
        'gotemplating.fn.crossplane.io/composition-resource-name: app-secret-{{ $slot }}',
        'observedAt: {{ $observedThrough | quote }}',
    )
    missing = [needle for needle in required if needle not in text]
    if missing:
        raise OverlapError("rotation source lacks remote-secret/CNPG proof: " + ", ".join(missing))
    if ('$previousCredentialRevoked := and $rotationStarted $overlapElapsed' in text or
            '(ne $previousPublishedVersion $previousStartVersion)' in text):
        raise OverlapError("rotation source revokes on time or resourceVersion rather than password proof")
    print("PASS slot mirrors and revocation require changed remote Secret RV plus matching CNPG application")


def check_cluster_readback_heartbeat(source: str | None = None) -> None:
    text = source if source is not None else composition_source()
    marker = 'gotemplating.fn.crossplane.io/composition-resource-name: database-cluster'
    start = text.find(marker)
    if start < 0:
        raise OverlapError("credential Cluster Object is missing")
    block = text[start:start + 900]
    heartbeat = 'platform.openkubes.ai/observe-through: {{ $observedThrough | quote }}'
    if heartbeat not in block:
        raise OverlapError("credential Cluster Object lacks the bounded provider-readback heartbeat")
    print("PASS managed-role status Cluster Object has bounded provider-readback heartbeat")


def evaluate(credentials: dict[str, Any], at: datetime) -> tuple[bool, str]:
    """Reader rule: may a consumer still authenticate with the PREVIOUS credential at `at`?

    Consumers need this to be answerable from status alone; that is the whole difference between
    an obligation stated in a contract and one a client has to infer. `previousCredentialAccepted`
    is the platform's answer, and this cross-checks it against the window so a stale or
    self-contradicting status is not believed.
    """
    active = credentials.get("activeRole")
    previous = credentials.get("previousRole")
    if active not in LOGIN_ROLES or previous not in LOGIN_ROLES:
        return False, "RolesNotAPair"
    if active == previous:
        return False, "NoDistinctPreviousRole"
    try:
        window = parse_duration(credentials.get("overlapWindow", ""), "overlapWindow")
    except OverlapError:
        return False, "OverlapWindowUnparseable"
    if window <= 0:
        return False, "OverlapWindowZero"

    accepted = credentials.get("previousCredentialAccepted")
    revoked = credentials.get("previousCredentialRevoked")
    if not isinstance(accepted, bool) or not isinstance(revoked, bool):
        return False, "AcceptanceOrRevocationNotDeclared"

    until = credentials.get("previousValidUntil")
    if until is None:
        # No rotation has happened yet, so there is no previous credential to accept or revoke.
        return (False, "NoRotationYet") if not accepted and not revoked else (False, "RotationStateWithoutRotation")

    try:
        expiry = datetime.strptime(until, RFC3339).replace(tzinfo=timezone.utc)
    except ValueError:
        return False, "PreviousValidUntilUnparseable"
    if accepted == revoked:
        return False, "AcceptanceContradictsRevocationProof"
    if accepted:
        # The deadline is an operator SLA, not evidence that PostgreSQL rejected the verifier.
        return (True, "PreviousCredentialAccepted") if at <= expiry else (True, "PreviousCredentialAcceptedRevocationOverdue")
    return False, "PreviousCredentialRevoked"


def previous_transition(start_rv: str, remote_rv: str, cnpg_rv: str,
                        start_digest: str, remote_digest: str) -> tuple[bool, bool]:
    """Model the Composition's old / in-flight / finalized previous-slot proof."""
    current_applied = bool(remote_rv) and cnpg_rv == remote_rv
    start_applied = bool(start_rv) and cnpg_rv == start_rv
    password_replaced = bool(remote_digest) and remote_digest != start_digest
    revoked = current_applied and password_replaced
    accepted = (current_applied or start_applied) and not revoked
    return accepted, revoked


def check_previous_transition() -> None:
    start_digest = "a" * 64
    old = previous_transition("201", "201", "201", start_digest, start_digest)
    inflight = previous_transition("201", "202", "201", start_digest, "b" * 64)
    finalized = previous_transition("201", "202", "202", start_digest, "b" * 64)
    metadata_only = previous_transition("201", "202", "202", start_digest, start_digest)
    if old != (True, False):
        raise OverlapError(f"old verifier transition wrong: {old}")
    if inflight != (True, False):
        raise OverlapError(f"in-flight replacement must retain old acceptance, got {inflight}")
    if finalized != (False, True):
        raise OverlapError(f"applied changed password must prove revocation, got {finalized}")
    if metadata_only != (True, False):
        raise OverlapError(f"metadata-only Secret update must not revoke, got {metadata_only}")
    print("PASS previous-slot transition: old and in-flight accepted; changed digest plus applied RV revoked")


def valid_credentials(now: datetime) -> dict[str, Any]:
    return {
        "applied": True,
        "reason": "CredentialApplied",
        "activeRole": "app_b",
        "previousRole": "app_a",
        "overlapWindow": "PT1H",
        "previousCredentialAccepted": True,
        "previousCredentialRevoked": False,
        "previousValidUntil": (now + timedelta(minutes=30)).strftime(RFC3339),
    }


def negative_controls() -> None:
    now = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)

    def same_role() -> dict[str, Any]:
        c = valid_credentials(now)
        c["previousRole"] = c["activeRole"]
        return c

    def zero_window() -> dict[str, Any]:
        c = valid_credentials(now)
        c["overlapWindow"] = "PT0S"
        return c

    def time_only_false_revocation() -> dict[str, Any]:
        """A deadline alone must never turn acceptance false."""
        c = valid_credentials(now)
        c["previousValidUntil"] = (now - timedelta(minutes=1)).strftime(RFC3339)
        c["previousCredentialAccepted"] = False
        # No remote Secret/CNPG replacement proof accompanies this false claim.
        c["previousCredentialRevoked"] = False
        return c

    def accepted_without_rotation() -> dict[str, Any]:
        c = valid_credentials(now)
        del c["previousValidUntil"]
        return c

    def unknown_role() -> dict[str, Any]:
        c = valid_credentials(now)
        c["activeRole"] = "app"
        return c

    def missing_boolean() -> dict[str, Any]:
        c = valid_credentials(now)
        del c["previousCredentialAccepted"]
        return c

    controls = {
        "previous role same as active": (same_role, "NoDistinctPreviousRole"),
        "zero-length overlap window": (zero_window, "OverlapWindowZero"),
        "time-only false revocation": (time_only_false_revocation, "AcceptanceContradictsRevocationProof"),
        "acceptance claimed with no rotation": (
            accepted_without_rotation,
            "RotationStateWithoutRotation",
        ),
        "owner role presented as a login slot": (unknown_role, "RolesNotAPair"),
        "acceptance not declared at all": (missing_boolean, "AcceptanceOrRevocationNotDeclared"),
    }
    for name, (build, expected) in controls.items():
        accepted, reason = evaluate(build(), now)
        if accepted:
            raise OverlapError(f"NEGATIVE CONTROL FAILED: {name} was accepted")
        if reason != expected:
            raise OverlapError(
                f"NEGATIVE CONTROL FAILED: {name} rejected for {reason!r}, expected {expected!r}"
            )
        print(f"NEGATIVE CONTROL PASS: {name}: {reason}")

    # The revocation proof must not regress to a clock-only assertion. Mutating Composition SOURCE
    # is what makes this a source test rather than a status fixture test.
    clock_only = composition_source().replace(
        '$previousCredentialRevoked := and $rotationStarted $previousCredentialApplied $previousPasswordReplaced',
        '$previousCredentialRevoked := and $rotationStarted $overlapElapsed',
    )
    try:
        check_rotation_source(clock_only)
    except OverlapError as exc:
        if "time or resourceVersion" not in str(exc) and "remote-secret/CNPG proof" not in str(exc):
            raise OverlapError(f"clock-only revocation rejected for wrong reason: {exc}") from exc
        print("NEGATIVE CONTROL PASS: elapsed time alone cannot claim previous credential revoked")
    else:
        raise OverlapError("NEGATIVE CONTROL FAILED: clock-only revocation source was accepted")

    rv_only = composition_source().replace(
        '$previousCredentialRevoked := and $rotationStarted $previousCredentialApplied $previousPasswordReplaced',
        '$previousCredentialRevoked := and $rotationStarted $previousCredentialApplied (ne $previousPublishedVersion $previousStartVersion)',
    )
    try:
        check_rotation_source(rv_only)
    except OverlapError as exc:
        if "resourceVersion" not in str(exc) and "remote-secret/CNPG proof" not in str(exc):
            raise OverlapError(f"RV-only revocation rejected for wrong reason: {exc}") from exc
        print("NEGATIVE CONTROL PASS: metadata-only Secret resourceVersion change cannot revoke")
    else:
        raise OverlapError("NEGATIVE CONTROL FAILED: resourceVersion-only revocation source was accepted")

    stale_observed_at = composition_source().replace(
        'observedAt: {{ $observedThrough | quote }}',
        'observedAt: {{ $operationalObservedAt | quote }}',
    )
    try:
        check_rotation_source(stale_observed_at)
    except OverlapError as exc:
        if "observedAt" not in str(exc):
            raise OverlapError(f"credential freshness source rejected for wrong reason: {exc}") from exc
        print("NEGATIVE CONTROL PASS: credential status cannot reuse a stale Cluster Ready timestamp")
    else:
        raise OverlapError("NEGATIVE CONTROL FAILED: stale credential observedAt source was accepted")

    missing_cluster_heartbeat = composition_source().replace(
        'gotemplating.fn.crossplane.io/composition-resource-name: database-cluster\n                # The workload Cluster\'s managed-role passwordStatus is credential evidence.\n                # Remote changes do not enqueue this management Object, so the same bounded\n                # heartbeat as the collector/slot mirrors forces normal provider read-back\n                # without alpha watch support.\n                platform.openkubes.ai/observe-through: {{ $observedThrough | quote }}',
        'gotemplating.fn.crossplane.io/composition-resource-name: database-cluster',
    )
    try:
        check_cluster_readback_heartbeat(missing_cluster_heartbeat)
    except OverlapError as exc:
        if "readback heartbeat" not in str(exc):
            raise OverlapError(f"Cluster heartbeat removal rejected for wrong reason: {exc}") from exc
        print("NEGATIVE CONTROL PASS: managed-role status cannot rely on an unrefreshed Cluster Object")
    else:
        raise OverlapError("NEGATIVE CONTROL FAILED: Cluster heartbeat removal was accepted")

    # The structural control: both slots on one Secret. Every status field still looks right, and
    # the overlap does not exist. Mutating the Composition SOURCE is what makes this a real test.
    shared = composition_source().replace('"%s-b" $spec.credentialsSecretRef.name', '"%s-a" $spec.credentialsSecretRef.name')
    try:
        check_role_structure(shared)
    except OverlapError as exc:
        if "share a passwordSecret" not in str(exc):
            raise OverlapError(
                f"NEGATIVE CONTROL FAILED: shared-secret case rejected for the wrong reason: {exc}"
            ) from exc
        print("NEGATIVE CONTROL PASS: both-slots-share-a-secret: rotating one would rotate both")
    else:
        raise OverlapError(
            "NEGATIVE CONTROL FAILED: two login roles sharing one passwordSecret was accepted; "
            "the overlap would be fictional while status looked correct"
        )

    # And the owner role being able to log in — the other way to lose the property.
    logins = composition_source().replace(
        f"""- name: {{{{ $ownerRole | quote }}}}
                          ensure: present
                          login: false""",
        f"""- name: {{{{ $ownerRole | quote }}}}
                          ensure: present
                          login: true""",
    )
    try:
        check_role_structure(logins)
    except OverlapError as exc:
        if "MUST be NOLOGIN" not in str(exc):
            raise OverlapError(f"owner-login case rejected for the wrong reason: {exc}") from exc
        print("NEGATIVE CONTROL PASS: owner role able to log in: a credential that never rotates")
    else:
        raise OverlapError(
            "NEGATIVE CONTROL FAILED: a login-capable owner role was accepted"
        )

    accepted, reason = evaluate(valid_credentials(now), now)
    if not accepted:
        raise OverlapError(f"a valid mid-overlap status was rejected: {reason}")
    print(f"PASS positive control: mid-overlap status accepted ({reason})")

    overdue = valid_credentials(now)
    overdue["previousValidUntil"] = (now - timedelta(minutes=1)).strftime(RFC3339)
    accepted, reason = evaluate(overdue, now)
    if not accepted or reason != "PreviousCredentialAcceptedRevocationOverdue":
        raise OverlapError(f"an overdue but unreplaced verifier must remain accepted, got {reason}")
    print(f"PASS honest overdue: {reason} — time alone never invents revocation")

    revoked = valid_credentials(now)
    revoked["previousCredentialAccepted"] = False
    revoked["previousCredentialRevoked"] = True
    accepted, reason = evaluate(revoked, now)
    if accepted or reason != "PreviousCredentialRevoked":
        raise OverlapError(f"a proven replacement must reject the previous credential, got {reason}")
    print(f"PASS proven replacement: {reason}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--negative-controls", action="store_true")
    args = parser.parse_args()
    try:
        if args.negative_controls:
            negative_controls()
        else:
            check_role_structure()
            check_declared_windows()
            check_xrd()
            check_rotation_source()
            check_cluster_readback_heartbeat()
            check_previous_transition()
    except OverlapError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
