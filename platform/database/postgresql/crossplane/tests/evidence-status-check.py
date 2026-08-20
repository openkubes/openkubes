#!/usr/bin/env python3
"""Validate the Database evidence state machine and readiness policy locally."""

from __future__ import annotations

import argparse
import copy
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml


STATES = {"Pending", "Valid", "Stale", "Failed", "Unknown"}
DIMENSIONS = ("operational", "protection", "recovery", "capability")
TESTS_DIR = Path(__file__).resolve().parent
CAPABILITY_DIR = TESTS_DIR.parent.parent
COMPOSITION_PATH = CAPABILITY_DIR / "crossplane/composition.yaml"
XRD_PATH = CAPABILITY_DIR / "crossplane/xrd.yaml"
RESTORE_FIXTURE_PATH = TESTS_DIR / "restoreverified-ok-robotics.yaml"
RECOVERY_SCENARIOS = frozenset(
    {
        "recovery-valid",
        "recovery-stale",
        "recovery-expired-no-prior",
        "recovery-rejected",
        "production-all-valid",
    }
)


class EvidenceError(ValueError):
    pass


class RenderedYamlLoader(yaml.SafeLoader):
    """Keep API date-time fields as strings, including deliberately invalid controls."""


RenderedYamlLoader.yaml_implicit_resolvers = {
    key: [
        resolver
        for resolver in resolvers
        if resolver[0] != "tag:yaml.org,2002:timestamp"
    ]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def protection_valid_reason(composition_text: str | None = None) -> str:
    """Read the named reason constant from Composition source, never rendered output."""
    source = composition_text if composition_text is not None else COMPOSITION_PATH.read_text()
    matches = re.findall(
        r'\{\{- \$protectionValidReason := "([A-Za-z0-9]+)" \}\}', source
    )
    if len(matches) != 1:
        raise EvidenceError(
            "Composition must declare exactly one named $protectionValidReason constant"
        )
    return matches[0]


def load_documents(path: str) -> list[dict[str, Any]]:
    if path == "-":
        stream = sys.stdin
        documents = list(yaml.safe_load_all(stream))
    else:
        with Path(path).open(encoding="utf-8") as stream:
            documents = list(yaml.safe_load_all(stream))
    return [document for document in documents if isinstance(document, dict)]


def find_database(documents: list[dict[str, Any]]) -> dict[str, Any]:
    matches = [
        document
        for document in documents
        if document.get("apiVersion") == "platform.openkubes.ai/v1alpha1"
        and document.get("kind") == "Database"
        and isinstance(document.get("status"), dict)
    ]
    if len(matches) != 1:
        raise EvidenceError(
            f"expected exactly one rendered Database with status, found {len(matches)}"
        )
    return matches[0]


def require_text(dimension: str, evidence: dict[str, Any], field: str) -> None:
    value = evidence.get(field)
    if not isinstance(value, str) or not value:
        raise EvidenceError(f"{dimension}.{field} must be a non-empty string")


def validate_dimension(
    name: str,
    evidence: dict[str, Any],
    previous: dict[str, Any] | None,
) -> None:
    state = evidence.get("state")
    if state not in STATES:
        raise EvidenceError(f"{name}.state {state!r} is outside the closed evidence enum")
    require_text(name, evidence, "reason")
    require_text(name, evidence, "observedAt")

    if state == "Stale":
        previous_state = previous.get("state") if previous else None
        if previous_state not in {"Valid", "Stale"}:
            raise EvidenceError(
                f"{name}.state Stale requires prior Valid evidence; got {previous_state!r}"
            )

    if name in {"operational", "capability"} and state in {"Valid", "Stale"}:
        require_text(name, evidence, "evidenceRef")

    if name == "protection" and state in {"Valid", "Stale"}:
        for field in ("validUntil", "evidenceRef", "backupId"):
            require_text(name, evidence, field)
        expected_reason = protection_valid_reason()
        if state == "Valid" and evidence.get("reason") != expected_reason:
            raise EvidenceError(
                "protection Valid requires the Composition's named execution, availability "
                f"and archiving reason {expected_reason!r}"
            )

    if name == "recovery" and state in {"Valid", "Stale"}:
        for field in (
            "validUntil",
            "evidenceRef",
            "backupId",
            "recoveryTarget",
            "verifierVersion",
        ):
            require_text(name, evidence, field)


def validate_database(
    database: dict[str, Any], previous_database: dict[str, Any] | None = None
) -> None:
    status = database.get("status", {})
    evidence = status.get("evidence")
    if not isinstance(evidence, dict):
        raise EvidenceError("status.evidence must be an object")

    previous_evidence: dict[str, Any] = {}
    if previous_database is not None:
        previous_evidence = previous_database.get("status", {}).get("evidence", {})

    for name in DIMENSIONS:
        current = evidence.get(name)
        if not isinstance(current, dict):
            raise EvidenceError(f"status.evidence.{name} must be an object")
        old = previous_evidence.get(name)
        validate_dimension(name, current, old if isinstance(old, dict) else None)

    policy = database.get("spec", {}).get("protection", {}).get("policyRef")
    if policy not in {"development", "production"}:
        raise EvidenceError(f"unknown protection policy {policy!r}")

    states = {name: evidence[name]["state"] for name in DIMENSIONS}
    if policy == "production":
        expected_ready = all(state == "Valid" for state in states.values())
    else:
        expected_ready = (
            states["operational"] == "Valid"
            and (
                states["recovery"] == "Valid"
                or (
                    states["protection"] == "Unknown"
                    and evidence["protection"]["reason"] == "AwaitingFirstBackup"
                    and states["recovery"] == "Unknown"
                    and evidence["recovery"]["reason"] == "VerificationPending"
                )
            )
        )

    service_ready = status.get("serviceReady")
    if not isinstance(service_ready, bool):
        raise EvidenceError("status.serviceReady must be boolean")
    if service_ready != expected_ready:
        raise EvidenceError(
            f"{policy} serviceReady must be {expected_ready} for evidence states {states}; "
            f"got {service_ready}"
        )
    require_text("status", status, "serviceReadyReason")


def synthetic_database() -> dict[str, Any]:
    observed = "2026-08-17T01:00:00Z"
    valid_until = "2026-08-18T01:00:00Z"
    return {
        "apiVersion": "platform.openkubes.ai/v1alpha1",
        "kind": "Database",
        "spec": {"protection": {"policyRef": "production"}},
        "status": {
            "evidence": {
                "operational": {
                    "state": "Valid",
                    "reason": "ClusterReady",
                    "observedAt": observed,
                    "evidenceRef": "Cluster/database-ok-robotics/ok-robotics",
                },
                "protection": {
                    "state": "Valid",
                    "reason": protection_valid_reason(),
                    "observedAt": observed,
                    "validUntil": valid_until,
                    "evidenceRef": "Backup/database-ok-robotics/ok-robotics-evidence",
                    "backupId": "20260817T010000",
                },
                "recovery": {
                    "state": "Valid",
                    "reason": "RestoreVerified",
                    "observedAt": observed,
                    "validUntil": valid_until,
                    "evidenceRef": "RestoreVerified/ok-145-drill",
                    "backupId": "20260817T010000",
                    "recoveryTarget": "2026-08-17T00:59:00Z",
                    "verifierVersion": "ok-db-restore-v1",
                },
                "capability": {
                    "state": "Valid",
                    "reason": "NoCapabilitiesRequested",
                    "observedAt": observed,
                    "evidenceRef": "Cluster/database-ok-robotics/ok-robotics#status.pgDataImageInfo",
                },
            },
            "serviceReady": True,
            "serviceReadyReason": "ProductionEvidenceValid",
        },
    }


def expect_failure(label: str, current: dict[str, Any], previous: dict[str, Any] | None = None) -> None:
    try:
        validate_database(current, previous)
    except EvidenceError as error:
        print(f"EXPECTED-FAIL {label}: {error}")
        return
    raise EvidenceError(f"negative control {label!r} unexpectedly passed")


def rfc3339(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def observed_manifest(documents: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    matches = [
        document
        for document in documents
        if document.get("status", {}).get("atProvider", {}).get("manifest", {}).get("kind")
        == kind
    ]
    if len(matches) != 1:
        raise EvidenceError(f"expected one observed {kind}, found {len(matches)}")
    return matches[0]["status"]["atProvider"]["manifest"]


def scenario_inputs(name: str, now: datetime) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    development_scenarios = {
        "development-bootstrap",
        *RECOVERY_SCENARIOS,
    }
    fixture = (
        "xr-ok-robotics.yaml"
        if name in development_scenarios
        else "xr-ok-robotics-production.yaml"
    )
    xr = yaml.safe_load((TESTS_DIR / fixture).read_text())
    if name == "production-all-valid":
        # Keep the independently authored Database/RestoreVerified identity pair.
        # Select production policy and the XRD's valid no-optional-capability case so
        # every readiness dimension has an actually emitted Valid path.
        xr["spec"]["protection"]["policyRef"] = "production"
        xr["spec"]["engine"]["capabilities"] = []
    observed = load_documents(str(TESTS_DIR / "observed-ok-robotics-valid.yaml"))
    cluster = observed_manifest(observed, "Cluster")
    backup = observed_manifest(observed, "Backup")
    schedule = observed_manifest(observed, "ScheduledBackup")
    store = observed_manifest(observed, "ObjectStore")

    recent = now - timedelta(hours=1)
    old = now - timedelta(days=5)
    # Recovery fixtures carry independently authored immutable identity constants.
    # Retain the observed fixture's own backupId for those cases; never rewrite the
    # admitted RestoreVerified identity fields from these compared observations.
    backup_id = (
        backup["status"]["backupId"]
        if name in RECOVERY_SCENARIOS
        else recent.strftime("%Y%m%dT%H%M%S")
    )
    cluster["status"]["conditions"][0]["lastTransitionTime"] = rfc3339(now - timedelta(days=6))
    backup["status"] = {
        "phase": "completed",
        "stoppedAt": rfc3339(recent),
        "backupId": backup_id,
    }
    schedule["status"] = {
        "lastCheckTime": rfc3339(now),
        "lastScheduleTime": rfc3339(now - timedelta(days=5)),
        "nextScheduleTime": rfc3339(now + timedelta(days=1)),
    }
    store["status"] = {
        "serverRecoveryWindow": {
            "ok-robotics": {
                "firstRecoverabilityPoint": rfc3339(now - timedelta(days=6)),
                "lastSuccessfulBackupTime": rfc3339(recent),
            }
        }
    }

    if name == "development-bootstrap":
        backup["status"] = {}
        schedule["status"] = {
            "lastCheckTime": rfc3339(now),
            "lastScheduleTime": rfc3339(now),
            "nextScheduleTime": rfc3339(now + timedelta(days=1)),
        }
        store["status"] = {}
    elif name in RECOVERY_SCENARIOS:
        if name == "recovery-stale":
            xr["status"] = {
                "evidence": {
                    "recovery": {
                        "state": "Valid",
                        "reason": "RestoreVerified",
                        "observedAt": rfc3339(now - timedelta(days=8)),
                        "validUntil": rfc3339(now - timedelta(days=7)),
                        "evidenceRef": "RestoreVerified/ok-robotics-valid",
                        "backupId": backup_id,
                        "recoveryTarget": "timeline=2,lsn=0/80001D0",
                        "verifierVersion": "prior-verifier",
                    }
                }
            }
        elif name == "recovery-expired-no-prior":
            xr["status"] = {
                "evidence": {
                    "recovery": {
                        "state": "Unknown",
                        "reason": "VerificationPending",
                        "observedAt": rfc3339(now - timedelta(days=9)),
                    }
                }
            }
    elif name == "execution-only":
        store["status"] = {}
    elif name == "backup-unavailable":
        store["status"]["serverRecoveryWindow"]["ok-robotics"].update(
            firstRecoverabilityPoint=rfc3339(recent + timedelta(minutes=1)),
            lastSuccessfulBackupTime=rfc3339(recent + timedelta(minutes=2)),
        )
    elif name == "continuous-archiving-failed":
        continuous_archiving = next(
            condition
            for condition in cluster["status"]["conditions"]
            if condition["type"] == "ContinuousArchiving"
        )
        continuous_archiving.update(
            status="False",
            reason="ContinuousArchivingFailing",
            lastTransitionTime=rfc3339(now - timedelta(minutes=10)),
        )
    elif name == "wal-archiving-unproven":
        cluster["status"]["conditions"] = [
            condition
            for condition in cluster["status"]["conditions"]
            if condition["type"] != "ContinuousArchiving"
        ]
    elif name == "pending":
        backup["status"] = {"phase": "running"}
    elif name == "observation-unavailable":
        backup["status"] = {
            "phase": "completed",
            "stoppedAt": rfc3339(recent),
        }
    elif name == "malformed-stopped-at":
        backup["status"] = {
            "phase": "completed",
            "stoppedAt": "2026-02-30T25:00:00Z",
            "backupId": "malformed-stopped-at",
        }
    elif name == "newer-backup-contained":
        backup["status"].update(
            stoppedAt=rfc3339(now - timedelta(hours=2)),
            backupId=(now - timedelta(hours=2)).strftime("%Y%m%dT%H%M%S"),
        )
    elif name == "last-failure-newer":
        store["status"]["serverRecoveryWindow"]["ok-robotics"][
            "lastFailedBackupTime"
        ] = rfc3339(now)
    elif name == "last-failure-equal":
        store["status"]["serverRecoveryWindow"]["ok-robotics"][
            "lastFailedBackupTime"
        ] = rfc3339(recent)
    elif name == "last-failure-older":
        store["status"]["serverRecoveryWindow"]["ok-robotics"][
            "lastFailedBackupTime"
        ] = rfc3339(now - timedelta(hours=2))
    elif name == "observation-not-caught-up":
        store["status"]["serverRecoveryWindow"]["ok-robotics"][
            "lastSuccessfulBackupTime"
        ] = rfc3339(recent - timedelta(minutes=1))
    elif name == "incoherent-window":
        store["status"]["serverRecoveryWindow"]["ok-robotics"].update(
            firstRecoverabilityPoint=rfc3339(recent + timedelta(minutes=2)),
            lastSuccessfulBackupTime=rfc3339(recent + timedelta(minutes=1)),
        )
    elif name == "all-bounds-equal":
        store["status"]["serverRecoveryWindow"]["ok-robotics"].update(
            firstRecoverabilityPoint=rfc3339(recent),
            lastSuccessfulBackupTime=rfc3339(recent),
        )
    elif name in {
        "expired-prior-valid",
        "expired-prior-unavailable",
        "expired-never-valid",
        "verification-overdue",
    }:
        expired_id = old.strftime("%Y%m%dT%H%M%S")
        backup["status"].update(stoppedAt=rfc3339(old), backupId=expired_id)
        store["status"]["serverRecoveryWindow"]["ok-robotics"].update(
            lastSuccessfulBackupTime=rfc3339(old)
        )
        if name in {"expired-prior-valid", "expired-prior-unavailable"}:
            xr["status"] = {
                "evidence": {
                    "protection": {
                        "state": "Valid",
                        "reason": protection_valid_reason(),
                        "observedAt": rfc3339(old),
                        "validUntil": rfc3339(old + timedelta(hours=24)),
                        "evidenceRef": "Backup/database-ok-robotics/ok-robotics-evidence",
                        "backupId": expired_id,
                    }
                }
            }
        if name == "expired-prior-unavailable":
            store["status"]["serverRecoveryWindow"]["ok-robotics"].update(
                firstRecoverabilityPoint=rfc3339(now - timedelta(days=4)),
                lastSuccessfulBackupTime=rfc3339(now - timedelta(days=1)),
            )
    elif name == "backup-failed":
        backup["status"] = {"phase": "failed", "stoppedAt": rfc3339(old)}
        store["status"] = {}
    elif name == "backup-overdue":
        backup["status"] = {}
        xr["status"] = {
            "evidence": {
                "protection": {
                    "state": "Unknown",
                    "reason": "AwaitingFirstBackup",
                    "observedAt": rfc3339(old),
                    "validUntil": rfc3339(old + timedelta(hours=1)),
                }
            }
        }
        store["status"] = {}
    elif name == "first-backup-deadline-persisted":
        backup["status"] = {}
        schedule["status"] = {
            "lastCheckTime": rfc3339(now),
            "lastScheduleTime": rfc3339(now),
            "nextScheduleTime": rfc3339(now + timedelta(days=1)),
        }
        store["status"] = {}
    elif name != "valid":
        raise EvidenceError(f"unknown render scenario {name!r}")

    return xr, observed


def render_scenario(
    name: str,
    now: datetime,
    composition_text: str | None = None,
    artifact_case: str | None = None,
) -> dict[str, Any]:
    xr, observed = scenario_inputs(name, now)
    with tempfile.TemporaryDirectory(prefix="ok-145-evidence-") as directory:
        work = Path(directory)
        xr_path = work / "xr.yaml"
        observed_path = work / "observed.yaml"
        extra_path = work / "extra.yaml"
        composition_path = work / "composition.yaml"
        xr_path.write_text(yaml.safe_dump(xr, sort_keys=False))
        observed_path.write_text(yaml.safe_dump_all(observed, sort_keys=False))
        composition_path.write_text(
            composition_text
            if composition_text is not None
            else COMPOSITION_PATH.read_text()
        )
        command = [
            "crossplane",
            "composition",
            "render",
            str(xr_path),
            str(composition_path),
            str(TESTS_DIR / "functions.yaml"),
            "--crossplane-version=v2.3.3",
            "--include-full-xr",
            f"--observed-resources={observed_path}",
        ]
        if name in RECOVERY_SCENARIOS:
            artifacts = load_documents(str(RESTORE_FIXTURE_PATH))
            if len(artifacts) != 2:
                raise EvidenceError(
                    f"RestoreVerified fixture must contain admitted and decoy documents; got {len(artifacts)}"
                )
            admitted, decoy = copy.deepcopy(artifacts)
            completed = now - (
                timedelta(days=8)
                if name in {"recovery-stale", "recovery-expired-no-prior"}
                else timedelta(hours=1)
            )
            admitted["spec"]["timing"].update(
                startedAt=rfc3339(completed - timedelta(minutes=1)),
                completedAt=rfc3339(completed),
                duration="PT60S",
            )
            decoy["spec"]["timing"].update(
                startedAt=rfc3339(completed),
                completedAt=rfc3339(completed + timedelta(minutes=1)),
                duration="PT60S",
            )
            selected_artifacts = [admitted, decoy]
            if artifact_case == "decoy":
                selected_artifacts = [decoy]
            elif artifact_case:
                tampered = admitted
                if artifact_case == "databaseRef.uid":
                    tampered["spec"]["databaseRef"]["uid"] = "tampered-database-uid"
                elif artifact_case == "sourceClusterRef.uid":
                    tampered["spec"]["sourceClusterRef"]["uid"] = "tampered-cluster-uid"
                elif artifact_case == "sourceSystemIdentifier":
                    tampered["spec"]["sourceSystemIdentifier"] = "tampered-system"
                elif artifact_case == "source.bucket":
                    tampered["spec"]["source"]["bucket"] = "tampered-bucket"
                elif artifact_case == "backupRef.uid":
                    tampered["spec"]["backupRef"]["uid"] = "tampered-backup-uid"
                elif artifact_case == "future completedAt":
                    future = now + timedelta(hours=1)
                    tampered["spec"]["timing"].update(
                        startedAt=rfc3339(future - timedelta(minutes=1)),
                        completedAt=rfc3339(future),
                    )
                else:
                    raise EvidenceError(f"unknown artifact case {artifact_case!r}")
                selected_artifacts = [tampered]
            extra_path.write_text(yaml.safe_dump_all(selected_artifacts, sort_keys=False))
            command.append(f"--extra-resources={extra_path}")
        result = subprocess.run(
            command,
            cwd=CAPABILITY_DIR,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise EvidenceError(
                f"render scenario {name} failed ({result.returncode}): {result.stderr.strip()}"
            )
        return find_database(
            [
                doc
                for doc in yaml.load_all(result.stdout, Loader=RenderedYamlLoader)
                if isinstance(doc, dict)
            ]
        )


def assert_dimension(
    label: str,
    database: dict[str, Any],
    dimension: str,
    expected_state: str,
    expected_reason: str,
) -> None:
    actual = database["status"]["evidence"][dimension]
    if (actual.get("state"), actual.get("reason")) != (
        expected_state,
        expected_reason,
    ):
        raise EvidenceError(
            f"{label}: expected {dimension}={expected_state}/{expected_reason}, "
            f"got {actual.get('state')}/{actual.get('reason')}"
        )


def assert_signal(
    label: str,
    database: dict[str, Any],
    signal: str,
    expected_state: str,
    expected_reason: str,
) -> None:
    actual = database["status"]["evidence"]["protection"]["signals"][signal]
    if (actual.get("state"), actual.get("reason")) != (
        expected_state,
        expected_reason,
    ):
        raise EvidenceError(
            f"{label}: expected protection.signals.{signal}="
            f"{expected_state}/{expected_reason}, got "
            f"{actual.get('state')}/{actual.get('reason')}"
        )


def replace_required(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise EvidenceError(f"{label}: expected one source mutation target, found {count}")
    return source.replace(old, new, 1)


def expect_reversion_failure(
    label: str,
    scenario: str,
    now: datetime,
    dimension: str,
    expected_state: str,
    expected_reason: str,
    composition_text: str,
    artifact_case: str | None = None,
) -> dict[str, Any]:
    reverted = render_scenario(
        scenario, now, composition_text=composition_text, artifact_case=artifact_case
    )
    try:
        assert_dimension(
            f"{label} logic reversion",
            reverted,
            dimension,
            expected_state,
            expected_reason,
        )
    except EvidenceError as error:
        print(f"EXPECTED-FAIL logic reversion {label}: {error}")
        return reverted
    raise EvidenceError(f"logic reversion {label!r} unexpectedly preserved the assertion")


def evaluate_authored_transition_cel(
    rule: str,
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> bool:
    """Evaluate the authored stale-transition CEL subset, failing on unknown syntax."""
    expression = " ".join(rule.split())
    replacements = (
        ("oldSelf.value().state", "previous_state"),
        ("oldSelf.hasValue()", "previous_present"),
        ("self.state", "current_state"),
        ("&&", " and "),
        ("||", " or "),
    )
    for old, new in replacements:
        expression = expression.replace(old, new)
    if re.search(r"[^A-Za-z0-9_\s\[\]'\"(),.!<>=-]", expression):
        raise EvidenceError(f"unsupported authored recovery CEL syntax: {rule}")
    try:
        result = eval(  # noqa: S307 - restricted source grammar and no builtins
            expression,
            {"__builtins__": {}},
            {
                "current_state": current.get("state"),
                "previous_present": previous is not None,
                "previous_state": previous.get("state") if previous else None,
            },
        )
    except (NameError, SyntaxError, TypeError) as error:
        raise EvidenceError(f"could not evaluate authored recovery CEL: {rule}") from error
    if not isinstance(result, bool):
        raise EvidenceError(f"authored recovery CEL did not return boolean: {rule}")
    return result


def xrd_compatibility_check(
    databases: dict[str, dict[str, Any]], now: datetime
) -> None:
    """Evaluate authored schema rules against actual render inputs and outputs."""
    xrd = yaml.safe_load(XRD_PATH.read_text())
    evidence_schema = xrd["spec"]["versions"][0]["schema"]["openAPIV3Schema"][
        "properties"
    ]["status"]["properties"]["evidence"]["properties"]
    for dimension in DIMENSIONS:
        allowed = set(evidence_schema[dimension]["properties"]["state"]["enum"])
        emitted = {
            database["status"]["evidence"][dimension]["state"]
            for database in databases.values()
        }
        if not emitted <= allowed:
            raise EvidenceError(
                f"XRD {dimension} enum rejects emitted states {sorted(emitted - allowed)}"
            )
        print(
            f"PASS static XRD enum compatibility {dimension}: "
            f"emitted={','.join(sorted(emitted))}"
        )

    rules = evidence_schema["recovery"].get("x-kubernetes-validations", [])
    if len(rules) != 1:
        raise EvidenceError("expected exactly one authored recovery transition CEL rule")
    rule = " ".join(rules[0]["rule"].split())
    for scenario, label in (
        ("recovery-expired-no-prior", "Unknown -> Pending"),
        ("recovery-stale", "Valid -> Stale"),
        ("recovery-valid", "absent -> Valid"),
    ):
        previous_xr, _ = scenario_inputs(scenario, now)
        previous = (
            previous_xr.get("status", {}).get("evidence", {}).get("recovery")
        )
        current = databases[scenario]["status"]["evidence"]["recovery"]
        if not evaluate_authored_transition_cel(rule, current, previous):
            raise EvidenceError(f"authored XRD recovery CEL rejected rendered {label}")
        print(f"PASS authored XRD recovery CEL: rendered {label} accepted")

    reverted_rule = replace_required(
        rule,
        "self.state != 'Stale'",
        "self.state == 'Stale'",
        "recovery CEL reversion",
    )
    previous_xr, _ = scenario_inputs("recovery-expired-no-prior", now)
    previous = previous_xr["status"]["evidence"]["recovery"]
    current = databases["recovery-expired-no-prior"]["status"]["evidence"][
        "recovery"
    ]
    if evaluate_authored_transition_cel(reverted_rule, current, previous):
        raise EvidenceError("reverted recovery CEL unexpectedly accepted Unknown -> Pending")
    print("EXPECTED-FAIL authored XRD recovery CEL reversion: Unknown -> Pending rejected")
    print("NOTE: authored CEL is evaluated locally; Kubernetes compilation is separate")


def render_scenario_tests(group: str = "core") -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    rendered: dict[str, dict[str, Any]] = {}
    valid_reason = protection_valid_reason()
    core_expectations = (
        ("development-bootstrap", "protection", "Unknown", "AwaitingFirstBackup"),
        ("recovery-valid", "recovery", "Valid", "RestoreVerified"),
        ("recovery-stale", "recovery", "Stale", "RestoreEvidenceExpired"),
        ("recovery-expired-no-prior", "recovery", "Pending", "FreshVerificationPending"),
        ("production-all-valid", "protection", "Valid", valid_reason),
        ("execution-only", "protection", "Unknown", "BackupAvailabilityUnproven"),
        ("valid", "protection", "Valid", valid_reason),
        ("expired-prior-valid", "protection", "Stale", "BackupEvidenceExpired"),
        ("expired-never-valid", "protection", "Pending", "FreshBackupEvidencePending"),
        ("expired-prior-unavailable", "protection", "Failed", "BackupUnavailable"),
        ("backup-unavailable", "protection", "Failed", "BackupUnavailable"),
        ("continuous-archiving-failed", "protection", "Failed", "ContinuousArchivingFailed"),
        ("backup-overdue", "protection", "Failed", "BackupOverdue"),
        ("first-backup-deadline-persisted", "protection", "Unknown", "AwaitingFirstBackup"),
        ("wal-archiving-unproven", "protection", "Unknown", "WALArchivingUnproven"),
        ("observation-unavailable", "protection", "Unknown", "ObservationUnavailable"),
        ("malformed-stopped-at", "protection", "Unknown", "ObservationTimestampInvalid"),
        ("pending", "protection", "Pending", "BackupInProgress"),
        ("newer-backup-contained", "protection", "Valid", valid_reason),
        ("backup-failed", "protection", "Failed", "BackupFailed"),
        ("verification-overdue", "recovery", "Failed", "VerificationOverdue"),
    )
    edge_expectations = (
        ("last-failure-newer", "protection", "Failed", "BackupFailed"),
        ("last-failure-equal", "protection", "Unknown", "BackupFailureTimeAmbiguous"),
        ("last-failure-older", "protection", "Valid", valid_reason),
        ("observation-not-caught-up", "protection", "Unknown", "BackupAvailabilityUnproven"),
        ("incoherent-window", "protection", "Unknown", "BackupAvailabilityUnproven"),
        ("all-bounds-equal", "protection", "Valid", valid_reason),
    )
    expectations = core_expectations if group == "core" else edge_expectations
    composition = COMPOSITION_PATH.read_text()
    for scenario, dimension, state, reason in expectations:
        database = render_scenario(scenario, now)
        rendered[scenario] = database
        assert_dimension(scenario, database, dimension, state, reason)
        print(f"PASS render {scenario}: {dimension}={state}/{reason}")

        # Exercise the Composition again after corrupting the exact reason logic
        # this assertion depends on. This changes renderer source, never its output,
        # and proves every scenario assertion can detect its own regression.
        reason_token = f'"{reason}"'
        if reason_token not in composition:
            raise EvidenceError(
                f"{scenario}: expected reason token {reason_token} is absent from Composition"
            )
        reverted_reason = f'LogicReverted{scenario.title().replace("-", "")}'
        reason_reversion = composition.replace(
            reason_token, f'"{reverted_reason}"'
        )
        expect_reversion_failure(
            f"{scenario} reason",
            scenario,
            now,
            dimension,
            state,
            reason,
            reason_reversion,
        )

    if group == "core":
        zero_time_scenarios = [
            scenario
            for scenario, database in rendered.items()
            if "0001-01-01" in yaml.safe_dump(database)
            or "0001-01-08" in yaml.safe_dump(database)
        ]
        if zero_time_scenarios:
            raise EvidenceError(
                f"zero-time instant published by scenarios {zero_time_scenarios}"
            )
        print("PASS rendered status matrix: no zero-time instant published")

        first_deadline = rendered["first-backup-deadline-persisted"]["status"][
            "evidence"
        ]["protection"].get("validUntil")
        if not isinstance(first_deadline, str) or not first_deadline:
            raise EvidenceError("first-backup deadline was not serialized before success")
        print(f"PASS first-backup deadline persisted before success: {first_deadline}")

        deadline_reversion = replace_required(
            composition,
            '            {{- $protectionValidUntil = $canonicalFirstBackupDeadline }}',
            '            {{- $protectionValidUntil = "" }}',
            "first-backup deadline persistence",
        )
        reverted_deadline = render_scenario(
            "first-backup-deadline-persisted",
            now,
            composition_text=deadline_reversion,
        )["status"]["evidence"]["protection"].get("validUntil")
        if reverted_deadline:
            raise EvidenceError(
                "first-backup deadline persistence reversion unexpectedly retained validUntil"
            )
        print(
            "EXPECTED-FAIL logic reversion first-backup deadline persistence: "
            "validUntil disappeared"
        )

        malformed = rendered["malformed-stopped-at"]["status"]["evidence"]["protection"]
        malformed_valid_until = malformed.get("validUntil", "")
        if malformed["state"] == "Failed" or str(malformed_valid_until).startswith(
            "0001-"
        ):
            raise EvidenceError("malformed stoppedAt fabricated Failed or zero-time validUntil")
        print("PASS malformed stoppedAt: Unknown, never Failed, no zero-time validUntil")

        recovery = rendered["recovery-valid"]["status"]["evidence"]["recovery"]
        if recovery.get("evidenceRef") != "RestoreVerified/ok-robotics-valid" or "99" in recovery.get("recoveryTarget", ""):
            raise EvidenceError("newer inadmissible fixture decoy displaced admitted evidence")
        print("PASS both RestoreVerified documents fed: newer inadmissible decoy rejected")

        production = rendered["production-all-valid"]
        assert_dimension(
            "production-all-valid",
            production,
            "recovery",
            "Valid",
            "RestoreVerified",
        )
        validate_database(production)
        if production["status"].get("serviceReady") is not True:
            raise EvidenceError("production-all-valid: rendered serviceReady=true is unreachable")
        print(
            "PASS render production-all-valid: protection=Valid, recovery=Valid, "
            "serviceReady=true"
        )

        mutations = (
            (
                "protection-valid",
                "valid",
                "protection",
                "Valid",
                valid_reason,
                '            {{- $archivingState = "Valid" }}\n            {{- $archivingReason = "ContinuousArchivingNotFailing" }}',
                '            {{- $archivingState = "Unknown" }}\n            {{- $archivingReason = "WALArchivingUnproven" }}',
            ),
            (
                "protection-stale",
                "expired-prior-valid",
                "protection",
                "Stale",
                "BackupEvidenceExpired",
                '            {{- $protectionState = "Stale" }}\n            {{- $protectionReason = "BackupEvidenceExpired" }}',
                '            {{- $protectionState = "Pending" }}\n            {{- $protectionReason = "FreshBackupEvidencePending" }}',
            ),
            (
                "protection-pending",
                "expired-never-valid",
                "protection",
                "Pending",
                "FreshBackupEvidencePending",
                '            {{- $protectionState = "Pending" }}\n            {{- $protectionReason = "FreshBackupEvidencePending" }}',
                '            {{- $protectionState = "Valid" }}\n            {{- $protectionReason = $protectionValidReason }}',
            ),
            (
                "recovery-expired-no-prior",
                "recovery-expired-no-prior",
                "recovery",
                "Pending",
                "FreshVerificationPending",
                '            {{- $recoveryState = "Pending" }}\n            {{- $recoveryReason = "FreshVerificationPending" }}',
                '            {{- $recoveryState = "Stale" }}\n            {{- $recoveryReason = "RestoreEvidenceExpired" }}',
            ),
        )
        for label, scenario, dimension, state, reason, old, new in mutations:
            mutated = replace_required(composition, old, new, label)
            expect_reversion_failure(
                label, scenario, now, dimension, state, reason, mutated
            )

        unavailable_precedence_reversion = replace_required(
            composition,
            '''            {{- if and (eq $availabilityState "Failed") (eq $availabilityReason "BackupUnavailable") }}
            {{- $protectionState = "Failed" }}
            {{- $protectionReason = "BackupUnavailable" }}
            {{- $protectionObservedAt = $availabilityObservedAt }}''',
            '''            {{- if and $protectionExpired $samePriorEvidence }}
            {{- $protectionState = "Stale" }}
            {{- $protectionReason = "BackupEvidenceExpired" }}
            {{- $protectionObservedAt = $availabilityObservedAt }}''',
            "BackupUnavailable precedence",
        )
        expect_reversion_failure(
            "BackupUnavailable outranks Stale",
            "expired-prior-unavailable",
            now,
            "protection",
            "Failed",
            "BackupUnavailable",
            unavailable_precedence_reversion,
        )

        malformed_reversion = replace_required(
            composition,
            '(eq $value (date $layout (toDate $layout $value)))',
            '(ne $value "")',
            "canonical-RFC3339-round-trip",
        )
        expect_reversion_failure(
            "canonical-RFC3339-round-trip",
            "malformed-stopped-at",
            now,
            "protection",
            "Unknown",
            "ObservationTimestampInvalid",
            malformed_reversion,
        )

        guard_sources = {
            "databaseRef.uid": '(eq (dig "uid" "" $databaseRef) $xr.metadata.uid)',
            "sourceClusterRef.uid": '(eq (dig "uid" "" $sourceClusterRef) (dig "metadata" "uid" "" $clusterManifest))',
            "sourceSystemIdentifier": '(eq (dig "sourceSystemIdentifier" "" $candidateSpec) (dig "systemID" "" $clusterStatus))',
            "source.bucket": '(eq (dig "bucket" "" $source) $store.bucket)',
            "backupRef.uid": '(eq (dig "uid" "" $backupRef) (dig "metadata" "uid" "" $backupManifest))',
            "future completedAt": '(not ((toDate $layout $canonicalCompletedAt).After now))',
        }
        for case, guard in guard_sources.items():
            rejected = render_scenario(
                "recovery-rejected", now, artifact_case=case
            )
            assert_dimension(case, rejected, "recovery", "Unknown", "VerificationPending")
            print(f"PASS RestoreVerified tamper rejected by renderer input: {case}")
            reverted_source = replace_required(
                composition, guard, "true", f"RestoreVerified guard {case}"
            )
            expect_reversion_failure(
                f"RestoreVerified guard {case}",
                "recovery-rejected",
                now,
                "recovery",
                "Unknown",
                "VerificationPending",
                reverted_source,
                artifact_case=case,
            )

        decoy = render_scenario("recovery-rejected", now, artifact_case="decoy")
        assert_dimension("decoy", decoy, "recovery", "Unknown", "VerificationPending")
        print("PASS RestoreVerified decoy-only input rejected")
        decoy_reversion = composition
        for guard in (
            guard_sources["databaseRef.uid"],
            guard_sources["sourceClusterRef.uid"],
            guard_sources["sourceSystemIdentifier"],
            guard_sources["backupRef.uid"],
        ):
            decoy_reversion = replace_required(decoy_reversion, guard, "true", "decoy guard")
        expect_reversion_failure(
            "RestoreVerified decoy guards",
            "recovery-rejected",
            now,
            "recovery",
            "Unknown",
            "VerificationPending",
            decoy_reversion,
            artifact_case="decoy",
        )

        for scenario in ("development-bootstrap", "recovery-valid"):
            validate_database(rendered[scenario])
            if rendered[scenario]["status"].get("serviceReady") is not True:
                raise EvidenceError(f"{scenario}: development serviceReady=true is unreachable")
            print(f"PASS render {scenario}: development serviceReady=true")

        contained = rendered["newer-backup-contained"]
        assert_signal(
            "newer-backup-contained",
            contained,
            "availability",
            "Valid",
            "BackupWindowContainsExecution",
        )
        print("PASS newer second backup remains inside the observed recovery window")
        for dimension in ("protection", "recovery"):
            reached = {
                database["status"]["evidence"][dimension]["state"]
                for database in rendered.values()
            }
            if reached != STATES:
                raise EvidenceError(
                    f"{dimension} state reachability missing {sorted(STATES - reached)}"
                )
            print(f"PASS {dimension} state reachability: {','.join(sorted(reached))}")
        xrd_compatibility_check(rendered, now)
    else:
        for scenario in ("last-failure-older", "all-bounds-equal"):
            assert_signal(
                scenario,
                rendered[scenario],
                "availability",
                "Valid",
                "BackupWindowContainsExecution",
            )
            print(f"PASS render {scenario}: availability=Valid/BackupWindowContainsExecution")


def self_test(group: str = "core") -> None:
    if group == "edges":
        render_scenario_tests(group)
        return
    positive = synthetic_database()

    pending_but_ready = copy.deepcopy(positive)
    pending_but_ready["status"]["evidence"]["protection"] = {
        "state": "Pending",
        "reason": "BackupInProgress",
        "observedAt": "2026-08-17T01:00:00Z",
    }
    expect_failure("production-pending-ready", pending_but_ready)

    development_capability_failed = copy.deepcopy(positive)
    development_capability_failed["spec"]["protection"]["policyRef"] = "development"
    development_capability_failed["status"]["evidence"]["protection"] = {
        "state": "Unknown",
        "reason": "AwaitingFirstBackup",
        "observedAt": "2026-08-17T01:00:00Z",
    }
    development_capability_failed["status"]["evidence"]["recovery"] = {
        "state": "Unknown",
        "reason": "VerificationPending",
        "observedAt": "2026-08-17T01:00:00Z",
    }
    development_capability_failed["status"]["evidence"]["capability"] = {
        "state": "Failed",
        "reason": "RequestedCapabilityAbsent",
        "observedAt": "2026-08-17T01:00:00Z",
    }
    validate_database(development_capability_failed)
    print("PASS development optional protection/capability: Pending/Failed stay visible")

    development_recovery_unknown = copy.deepcopy(development_capability_failed)
    development_recovery_unknown["status"]["evidence"]["recovery"] = {
        "state": "Unknown",
        "reason": "ObservationUnavailable",
        "observedAt": "2026-08-17T01:00:00Z",
    }
    expect_failure("development-recovery-unknown-ready", development_recovery_unknown)

    stale_without_valid = copy.deepcopy(positive)
    stale_without_valid["status"]["evidence"]["protection"]["state"] = "Stale"
    stale_without_valid["status"]["serviceReady"] = False
    stale_without_valid["status"]["serviceReadyReason"] = "EvidencePolicyUnsatisfied"
    never_valid = copy.deepcopy(positive)
    never_valid["status"]["evidence"]["protection"] = {
        "state": "Unknown",
        "reason": "AwaitingFirstBackup",
        "observedAt": "2026-08-17T00:00:00Z",
    }
    never_valid["status"]["serviceReady"] = False
    expect_failure("stale-without-prior-valid", stale_without_valid, never_valid)

    render_scenario_tests(group)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("rendered", nargs="?", help="rendered YAML, or - for stdin")
    parser.add_argument("--previous", help="previous rendered Database YAML")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--self-test-group", choices=("core", "edges"), default="core")
    args = parser.parse_args()

    try:
        if args.self_test:
            self_test(args.self_test_group)
            return 0
        if not args.rendered:
            parser.error("rendered is required unless --self-test is used")
        database = find_database(load_documents(args.rendered))
        previous = None
        if args.previous:
            previous = find_database(load_documents(args.previous))
        validate_database(database, previous)
        evidence = database["status"]["evidence"]
        states = ",".join(f"{name}={evidence[name]['state']}" for name in DIMENSIONS)
        policy = database["spec"]["protection"]["policyRef"]
        ready = str(database["status"]["serviceReady"]).lower()
        print(
            "PASS Database evidence status and serviceReady policy: "
            f"policy={policy} serviceReady={ready} {states}"
        )
        return 0
    except (EvidenceError, OSError, yaml.YAMLError) as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
