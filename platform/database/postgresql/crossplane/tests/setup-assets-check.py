#!/usr/bin/env python3
"""Guard clean installation and the collector's two-cluster authority boundary."""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
MAKEFILE = ROOT / "Makefile"
COMPOSITION = ROOT / "crossplane/composition.yaml"
COLLECTOR = ROOT / "collector/measure-wal-exposure.sh"

REQUIRED_SETUP = {
    "crossplane/restoreverified-crd.yaml",
    "crossplane/capabilityverified-crd.yaml",
    "crossplane/datapolicy-crd.yaml",
    "crossplane/verificationprofile-crd.yaml",
    "crossplane/databasetargetprofile-crd.yaml",
    "crossplane/rbac/restoreverified-writer-clusterrole.yaml",
    "crossplane/rbac/restoreverified-writer-clusterrolebinding.yaml",
    "crossplane/rbac/restoreverified-reader-clusterrole.yaml",
    "crossplane/rbac/restoreverified-reader-clusterrolebinding.yaml",
    "crossplane/rbac/evidence-reader-clusterrole.yaml",
    "crossplane/rbac/verificationprofile-writer-clusterrole.yaml",
    "crossplane/rbac/verificationprofile-writer-clusterrolebinding.yaml",
    "crossplane/claim-admission-policy.yaml",
    "crossplane/xrd.yaml",
    "crossplane/composition.yaml",
}
FORBIDDEN_AUTHORITY = (
    "archive-freshness-publisher-token",
    "--token=",
    "resources: [pods/exec]",
    "kind: ArchiveFreshness",
)


class CheckError(ValueError):
    pass


def variable(text: str, name: str) -> set[str]:
    lines = text.splitlines()
    prefix = name + " :="
    try:
        index = next(i for i, line in enumerate(lines) if line.startswith(prefix))
    except StopIteration as exc:
        raise CheckError(f"Makefile must define {name} as the single install inventory") from exc
    parts = [lines[index].split(":=", 1)[1].strip()]
    while parts[-1].endswith("\\"):
        parts[-1] = parts[-1][:-1].strip()
        index += 1
        if index >= len(lines):
            raise CheckError(f"unterminated Makefile continuation for {name}")
        parts.append(lines[index].strip())
    tokens = set(" ".join(parts).split())
    expanded = set()
    for token in tokens:
        ref = re.fullmatch(r"\$\(([^)]+)\)", token)
        if ref:
            expanded |= variable(text, ref.group(1))
        else:
            expanded.add(token)
    return expanded


def check(makefile: str, composition: str, collector: str) -> None:
    installed = variable(makefile, "SETUP_FILES")
    missing = REQUIRED_SETUP - installed
    if missing:
        raise CheckError("setup inventory missing: " + ", ".join(sorted(missing)))
    if "TARGET_FILE = crossplane/targets/$(CLUSTER).yaml" not in makefile:
        raise CheckError("target enrollment path must derive beneath crossplane/targets from CLUSTER")
    for guard in ('CLUSTER must be one DNS label', 'test -f "$(TARGET_FILE)"'):
        if guard not in makefile:
            raise CheckError(f"target enrollment path guard missing: {guard}")
    if '$$MK apply --dry-run=server -f "$(TARGET_FILE)"' not in makefile or '$$MK apply -f "$(TARGET_FILE)"' not in makefile:
        raise CheckError("setup must server-validate and apply the reviewed target enrollment")
    for preflight in ("endpointCA", "ca.crt", "ACCESS_KEY_ID", "ACCESS_SECRET_KEY", "--kubeconfig=/dev/stdin"):
        if preflight not in makefile:
            raise CheckError(f"target workload Secret preflight missing: {preflight}")
    for naming_term in (
        '["metadata"]["name"]', "len(n) <= 52", "p=n[:43]", "hashlib.sha256",
        'p=p[:-1] if p.endswith("-") else p',
        'p=p[:-1] if p.endswith(".") else p',
    ):
        if naming_term not in makefile:
            raise CheckError(f"writer preflight must derive the Composition database name: {naming_term}")
    if 'rstrip("-.")' in makefile:
        raise CheckError("writer preflight must apply the Composition's sequential trimSuffix operations exactly")
    if 'writer_secret="ok-db-backups-$(CLUSTER)-writer"' in makefile:
        raise CheckError("writer preflight must use claimName-derived dbName, not clusterRef")

    # Legal long DNS names can put consecutive '-' at the truncation boundary. Sprig's
    # trimSuffix removes one suffix per call; Python rstrip would silently preflight a
    # different Secret. Keep this counterexample coupled to the source checks above.
    adversarial = "a" * 41 + "--" + "b" * 12
    prefix = adversarial[:43]
    if prefix.endswith("-"):
        prefix = prefix[:-1]
    if prefix.endswith("."):
        prefix = prefix[:-1]
    expected = prefix + "-" + hashlib.sha256(adversarial.encode()).hexdigest()[:8]
    if not expected.startswith("a" * 41 + "--"):
        raise CheckError("adversarial database-name vector no longer exercises one-suffix trimming")
    if adversarial[:43].rstrip("-.") + "-" + hashlib.sha256(adversarial.encode()).hexdigest()[:8] == expected:
        raise CheckError("adversarial database-name vector does not distinguish rstrip")
    target_docs = list(yaml.safe_load_all((ROOT / "crossplane/targets/ok-robotics.yaml").read_text()))
    if len(target_docs) != 2 or {d.get("kind") for d in target_docs} != {"ProviderConfig", "DatabaseTargetProfile"}:
        raise CheckError("target enrollment must contain exactly ProviderConfig and DatabaseTargetProfile")
    provider = next(d for d in target_docs if d["kind"] == "ProviderConfig")
    profile = next(d for d in target_docs if d["kind"] == "DatabaseTargetProfile")
    if provider["metadata"]["name"] != profile["metadata"]["name"] or profile["spec"]["clusterRef"] != provider["metadata"]["name"]:
        raise CheckError("target ProviderConfig/profile/clusterRef identities must match")
    credentials = provider.get("spec", {}).get("credentials", {})
    if credentials.get("source") != "Secret" or set(credentials.get("secretRef", {})) != {"namespace", "name", "key"}:
        raise CheckError("target ProviderConfig must contain only the registration Secret reference")
    if "crossplane/examples/verificationprofile-restore-drill.yaml" in installed:
        raise CheckError("setup must not manufacture the separate verification-method approval")
    if "approve-verification-profile: require-mgmt-approval" not in makefile:
        raise CheckError("verification method needs its own approval-gated Make target")
    if "for f in $(SETUP_FILES)" not in makefile:
        raise CheckError("setup dry-run must consume SETUP_FILES rather than a second hand-written list")
    if "for f in $(CONTRACT_CRDS)" not in makefile or "for f in $(PLATFORM_RBAC)" not in makefile:
        raise CheckError("setup apply must consume the shared CRD and RBAC inventories")
    for path in REQUIRED_SETUP:
        if not (ROOT / path).is_file():
            raise CheckError(f"setup inventory names missing file: {path}")
    for forbidden in FORBIDDEN_AUTHORITY:
        if forbidden in composition or forbidden in collector:
            raise CheckError(f"collector authority regression: {forbidden}")
    required_composition = (
        "managementPolicies: [\"*\"]",
        "resourceNames: [{{ $collectorObservationName | quote }}]",
        "resourceNames: [{{ $dbName | quote }}]",
        "verbs: [get, update, patch]",
        "cnpg.io/instanceRole: primary",
        "cnpg_collector_pg_wal_archive_status{value=\"ready\"}",
        "gotemplating.fn.crossplane.io/composition-resource-name: collector-observation",
        "platform.openkubes.ai/observe-through: {{ $observedThrough | quote }}",
        "(eq (dig \"probeDigest\" \"\" $collectorObservationData) $rpoProbeDigest)",
        "(eq (dig \"verifierVersion\" \"\" $collectorObservationData) $rpoVerifierVersion)",
        "(eq (dig \"clusterUid\" \"\" $collectorObservationData) (dig \"metadata\" \"uid\" \"\" $clusterManifest))",
    )
    for required in required_composition:
        if required not in composition:
            raise CheckError(f"collector boundary missing: {required}")
    if "managementPolicies: [Create, Observe]" in composition or "data: {}" in composition:
        raise CheckError("collector mailbox must leave data fields collector-owned under normal provider polling")
    if "archive-freshness:" in composition:
        raise CheckError("RPO must not accept independently writable ArchiveFreshness ExtraResources")
    shared_parser_terms = (
        "exposure = 0 if pending else min(math.ceil(since), timeout)",
        "exposure = pending>0 ? unproven : min(ceil(seconds_since_last_archive), archive_timeout)",
        "wal-exposure-metrics-collector/0.2.0",
    )
    for term in shared_parser_terms:
        if term not in composition or term not in collector:
            raise CheckError(f"runtime and testable collector parser drifted: {term}")
    role = yaml.safe_load(
        (ROOT / "crossplane/rbac/verificationprofile-writer-clusterrole.yaml").read_text()
    )
    if role.get("rules") != [{
        "apiGroups": ["platform.openkubes.ai"],
        "resources": ["verificationprofiles"],
        "verbs": ["create", "get", "list", "watch"],
    }]:
        raise CheckError("verification-method authority must be create/read only")


def negative_controls(makefile: str, composition: str, collector: str) -> None:
    cases = [
        (
            "missing capability CRD",
            makefile.replace("crossplane/capabilityverified-crd.yaml", "crossplane/omitted-crd.yaml"),
            composition,
            collector,
            "setup inventory missing",
        ),
        (
            "missing target profile CRD",
            makefile.replace("crossplane/databasetargetprofile-crd.yaml", "crossplane/omitted-target-crd.yaml"),
            composition,
            collector,
            "setup inventory missing",
        ),
        (
            "target path traversal guard removed",
            makefile.replace("CLUSTER must be one DNS label", "target name unchecked"),
            composition,
            collector,
            "path guard missing",
        ),
        (
            "writer preflight collapses repeated suffix punctuation",
            makefile.replace('p=p[:-1] if p.endswith("-") else p; p=p[:-1] if p.endswith(".") else p', 'p=p.rstrip("-.")'),
            composition,
            collector,
            "Composition database name",
        ),
        (
            "writer preflight uses clusterRef instead of claimName",
            makefile.replace('["metadata"]["name"]', '["spec"]["clusterRef"]'),
            composition,
            collector,
            "Composition database name",
        ),
        (
            "target CA preflight removed",
            makefile.replace('"$$endpoint_ca:ca.crt"', '"$$endpoint_ca:missing"'),
            composition,
            collector,
            "Secret preflight missing",
        ),
        (
            "target writer access-key preflight removed",
            makefile.replace('"$$writer_secret:ACCESS_KEY_ID"', '"$$writer_secret:OTHER"'),
            composition,
            collector,
            "Secret preflight missing",
        ),
        (
            "target writer secret-key preflight removed",
            makefile.replace('"$$writer_secret:ACCESS_SECRET_KEY"', '"$$writer_secret:OTHER"'),
            composition,
            collector,
            "Secret preflight missing",
        ),
        (
            "shared management token",
            makefile,
            composition + "\narchive-freshness-publisher-token\n",
            collector,
            "authority regression",
        ),
        (
            "secret in argv",
            makefile,
            composition + "\nkubectl --token=$(cat /secret)\n",
            collector,
            "authority regression",
        ),
        (
            "pods exec returns",
            makefile,
            composition + "\nresources: [pods/exec]\n",
            collector,
            "authority regression",
        ),
        (
            "provider readback heartbeat removed",
            makefile,
            composition.replace("platform.openkubes.ai/observe-through: {{ $observedThrough | quote }}", "# heartbeat removed"),
            collector,
            "boundary missing",
        ),
        (
            "name scope removed",
            makefile,
            composition.replace("resourceNames: [{{ $collectorObservationName | quote }}]", "# resourceNames removed"),
            collector,
            "boundary missing",
        ),
        (
            "self-asserted evidence API returns",
            makefile,
            composition + "\nkind: ArchiveFreshness\n",
            collector,
            "authority regression",
        ),
        (
            "runtime parser invents pending WAL age",
            makefile,
            composition.replace(
                "exposure = 0 if pending else min(math.ceil(since), timeout)",
                "exposure = math.ceil(since) if pending else min(math.ceil(since), timeout)",
            ),
            collector,
            "parser drifted",
        ),
    ]
    for name, mutated_makefile, mutated_composition, mutated_collector, expected in cases:
        try:
            check(mutated_makefile, mutated_composition, mutated_collector)
        except CheckError as exc:
            if expected not in str(exc):
                raise CheckError(f"negative control {name!r} failed for wrong reason: {exc}") from exc
            print(f"NEGATIVE CONTROL PASS: {name}: {exc}")
        else:
            raise CheckError(f"negative control did not fail: {name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--negative-controls", action="store_true")
    args = parser.parse_args()
    makefile = MAKEFILE.read_text()
    composition = COMPOSITION.read_text()
    collector = COLLECTOR.read_text()
    if args.negative_controls:
        negative_controls(makefile, composition, collector)
    else:
        check(makefile, composition, collector)
        print("PASS: setup inventory is complete; collector has no management token, cross-DB writer, or pods/exec authority")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
