#!/usr/bin/env python3
"""Bounded P1 Platform failure, observation, and exact restoration."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import yaml


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "platform-p1-execution-candidate-v1.yaml"
SEMANTICS_PATH = HERE / "controlled_failure_semantics_v1.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


SEMANTICS = load_module("ok141_platform_failure_semantics", SEMANTICS_PATH)


class P1Error(RuntimeError):
    pass


def sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def digest(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def canonical_digest(value: Any) -> str:
    return sha_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise P1Error("timestamp lacks timezone")
    return parsed.astimezone(dt.timezone.utc)


def read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise P1Error(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise P1Error(f"{context}: expected {expected!r}, got {actual!r}")


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = read_yaml(path)
    expect(value.get("kind"), "ControlledPlatformFailureExecutionCandidate", "kind")
    spec = value["spec"]
    expect(spec["state"], "PREPARED-NO-GO", "state")
    expect(
        digest(HERE / "platform-failure-candidate-v1.yaml"),
        spec["sourceCandidateDigest"],
        "source candidate",
    )
    expect(digest(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool")
    expect(digest(SEMANTICS_PATH), spec["semanticsDigest"], "semantics")
    expect(spec["target"]["name"], "disposable-ok141-observability-dashboards", "target")
    expect(spec["fault"]["baselinePath"], "dashboards", "baseline path")
    expect(
        spec["fault"]["injectedPath"],
        "dashboards/ok141-controlled-failure-missing",
        "fault path",
    )
    authorization = spec["authorization"]
    expect(authorization["decision"], "NO-GO", "authorization")
    if any(item for key, item in authorization.items() if key.endswith("Granted")):
        raise P1Error("candidate grants live authority")
    return value


def validate_grant(
    candidate_path: Path,
    grant_path: Path,
    current: dt.datetime | None = None,
) -> dict[str, Any]:
    validate_candidate(candidate_path)
    grant = read_yaml(grant_path)
    expect(grant.get("kind"), "ControlledPlatformFailureGrant", "grant kind")
    spec = grant["spec"]
    expect(spec["decision"], "GO", "grant decision")
    expect(spec["candidateDigest"], digest(candidate_path), "candidate digest")
    expect(spec["authority"], "github:arashkaffamanesh", "authority")
    required = (
        "sharedCredentialUseGranted",
        "workloadCredentialUseGranted",
        "failureInjectionGranted",
        "boundedObservationGranted",
        "exactRestoreGranted",
    )
    forbidden = (
        "deleteGranted",
        "retryGranted",
        "generalCleanupGranted",
        "outageGranted",
        "evidencePublicationGranted",
    )
    if any(spec.get(key) is not True for key in required):
        raise P1Error("grant lacks required authority")
    if any(spec.get(key) is not False for key in forbidden):
        raise P1Error("grant expands forbidden authority")
    if spec.get("singleRun") is not True or spec.get("consumed") is not False:
        raise P1Error("grant is not an unused single run")
    point = current or dt.datetime.now(dt.timezone.utc)
    issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= point <= expires or expires - issued > dt.timedelta(minutes=45):
        raise P1Error("grant inactive or exceeds 45 minutes")
    return grant


def safe_file(path: Path, expected_digest: str, *, credential: bool = False) -> None:
    if path.is_symlink() or not path.is_file() or digest(path) != expected_digest:
        raise P1Error("bound file identity mismatch")
    if credential and (path.stat().st_mode & 0o777) != 0o600:
        raise P1Error("unsafe kubeconfig mode")


def safe_replace_document(current: dict[str, Any], new_spec: dict[str, Any]) -> bytes:
    metadata = current.get("metadata", {})
    if not metadata.get("uid") or not metadata.get("resourceVersion"):
        raise P1Error("object lacks UID/resourceVersion")
    result = copy.deepcopy(current)
    result.pop("status", None)
    result["metadata"].pop("managedFields", None)
    result["metadata"].pop("selfLink", None)
    result["spec"] = copy.deepcopy(new_spec)
    return json.dumps(result, sort_keys=True, separators=(",", ":")).encode()


def fault_spec(baseline: dict[str, Any], baseline_path: str, injected_path: str) -> dict[str, Any]:
    source = baseline.get("source", {})
    if source.get("path") != baseline_path:
        raise P1Error("baseline path precondition failed")
    result = copy.deepcopy(baseline)
    result["source"]["path"] = injected_path
    return result


def raw(
    client: Path,
    kubeconfig: Path,
    verb: str,
    uri: str,
    payload: bytes | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    command = [str(client), "--kubeconfig", str(kubeconfig), verb, "--raw", uri]
    if payload is not None:
        command.extend(["--filename", "-"])
    result = runner(
        command,
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise P1Error(f"bounded {verb} failed; output suppressed")
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise P1Error("API returned non-object")
    return value


def clients(spec: dict[str, Any]) -> tuple[Path, Path, Path, Path]:
    shared_client = Path(spec["shared"]["clientPath"])
    workload_client = Path(spec["workload"]["clientPath"])
    shared_config = Path(spec["shared"]["kubeconfigPath"])
    workload_config = Path(spec["workload"]["kubeconfigPath"])
    safe_file(shared_client, spec["shared"]["clientDigest"])
    safe_file(workload_client, spec["workload"]["clientDigest"])
    safe_file(shared_config, spec["shared"]["kubeconfigDigest"], credential=True)
    safe_file(workload_config, spec["workload"]["kubeconfigDigest"], credential=True)
    return shared_client, workload_client, shared_config, workload_config


def read_state(
    spec: dict[str, Any],
    bound_clients: tuple[Path, Path, Path, Path],
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    shared_client, workload_client, shared_config, workload_config = bound_clients
    applications = {
        name: raw(shared_client, shared_config, "get", uri, runner=runner)
        for name, uri in spec["queries"]["applications"].items()
    }
    protected = raw(
        workload_client,
        workload_config,
        "get",
        spec["queries"]["protectedDashboard"],
        runner=runner,
    )
    return {"applications": applications, "protected": protected}


def blocking_condition(application: dict[str, Any], condition_type: str) -> dict[str, Any]:
    return next(
        (
            item
            for item in application.get("status", {}).get("conditions", [])
            if item.get("type") == condition_type
        ),
        {},
    )


def condition_after(condition: dict[str, Any], fence: str) -> bool:
    value = condition.get("lastTransitionTime")
    if not isinstance(value, str):
        return False
    try:
        return parse_time(value) >= parse_time(fence)
    except (ValueError, P1Error):
        return False


def baseline_ready(spec: dict[str, Any], state: dict[str, Any]) -> bool:
    applications = list(state["applications"].values())
    return SEMANTICS.platform_ready(
        applications,
        expected_revision=spec["fixture"]["sourceRevision"],
    ) and canonical_digest(state["protected"].get("data", {})) == spec["protectedTarget"][
        "dataDigest"
    ]


def preflight(
    candidate_path: Path,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    spec = candidate["spec"]
    bound_clients = clients(spec)
    state = read_state(spec, bound_clients, runner)
    target = state["applications"]["dashboards"]
    expect(target.get("metadata", {}).get("name"), spec["target"]["name"], "name")
    expect(target.get("metadata", {}).get("namespace"), spec["target"]["namespace"], "namespace")
    expect(canonical_digest(target.get("spec", {})), spec["target"]["baselineSpecDigest"], "spec")
    annotations = target.get("metadata", {}).get("annotations", {})
    for key, expected in (
        ("openkubes.io/intent-revision", spec["fixture"]["R"]),
        ("openkubes.io/platform-revision", spec["fixture"]["P"]),
        ("openkubes.io/execution-fixture", spec["fixture"]["fixtureDigest"]),
    ):
        expect(annotations.get(key), expected, key)
    if not baseline_ready(spec, state):
        raise P1Error("Platform baseline is not ready")
    return {
        "state": "PASS-READY-NO-WRITES",
        "applicationCount": 3,
        "PlatformReady": True,
        "protectedDashboardCurrent": True,
    }


def write_exclusive(path: Path, value: dict[str, Any]) -> None:
    payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)


def execute(
    candidate_path: Path,
    grant_path: Path,
    runner: Callable[..., Any] = subprocess.run,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant = validate_grant(candidate_path, grant_path)
    spec, grant_spec = candidate["spec"], grant["spec"]
    bound_clients = clients(spec)
    shared_client, _, shared_config, _ = bound_clients
    output = Path(grant_spec["outputPath"])
    if output.exists() or output.is_symlink():
        raise P1Error("exclusive evidence output already exists")
    evidence: dict[str, Any] = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "ControlledPlatformFailureEvidence",
        "candidateDigest": digest(candidate_path),
        "grantID": grant_spec["grantID"],
        "startedAt": now(),
        "state": "STARTED",
        "faultWritten": False,
        "faultObserved": False,
        "restoreWritten": False,
        "recoveryObserved": False,
        "PlatformReadyDuringFault": None,
        "PlatformReadyAfterRestore": None,
        "coreAndAlertingReadyDuringFault": False,
        "protectedTargetUnchanged": False,
        "runnerRepairPerformed": False,
        "directTargetMutationPerformed": False,
        "deletePerformed": False,
        "retryPerformed": False,
        "rawObjectsRetained": False,
        "credentialPayloadRetained": False,
    }
    fault_written = False
    baseline: dict[str, Any] | None = None
    target_uri = spec["queries"]["applications"]["dashboards"]
    try:
        evidence["preflight"] = preflight(candidate_path, runner)
        initial = read_state(spec, bound_clients, runner)
        baseline = initial["applications"]["dashboards"]
        baseline_uid = baseline["metadata"]["uid"]
        baseline_spec = copy.deepcopy(baseline["spec"])
        changed_spec = fault_spec(
            baseline_spec,
            spec["fault"]["baselinePath"],
            spec["fault"]["injectedPath"],
        )
        fault_fence = now()
        changed = raw(
            shared_client,
            shared_config,
            "replace",
            target_uri,
            safe_replace_document(baseline, changed_spec),
            runner,
        )
        if (
            changed.get("metadata", {}).get("uid") != baseline_uid
            or changed.get("metadata", {}).get("resourceVersion")
            == baseline.get("metadata", {}).get("resourceVersion")
            or canonical_digest(changed.get("spec", {})) != canonical_digest(changed_spec)
        ):
            raise P1Error("fault optimistic-concurrency postcondition failed")
        fault_written = True
        evidence["faultWritten"] = True

        for iteration in range(1, spec["observation"]["failureMaximumIterations"] + 1):
            state = read_state(spec, bound_clients, runner)
            applications = state["applications"]
            dashboards = applications["dashboards"]
            condition = blocking_condition(
                dashboards, spec["expectedFailure"]["conditionType"]
            )
            other_ready = all(
                SEMANTICS.application_ready(
                    applications[name],
                    expected_revision=spec["fixture"]["sourceRevision"],
                    expected_path=SEMANTICS.APPLICATION_PATHS[
                        applications[name]["metadata"]["name"]
                    ],
                )
                for name in ("core", "alerting")
            )
            protected_unchanged = (
                canonical_digest(state["protected"].get("data", {}))
                == spec["protectedTarget"]["dataDigest"]
            )
            if (
                canonical_digest(dashboards.get("spec", {}))
                == canonical_digest(changed_spec)
                and condition
                and condition_after(condition, fault_fence)
                and not SEMANTICS.platform_ready(
                    list(applications.values()),
                    expected_revision=spec["fixture"]["sourceRevision"],
                )
                and other_ready
                and protected_unchanged
            ):
                evidence["faultObserved"] = True
                evidence["failureObservationIteration"] = iteration
                evidence["PlatformReadyDuringFault"] = False
                evidence["coreAndAlertingReadyDuringFault"] = True
                evidence["protectedTargetUnchanged"] = True
                break
            if iteration < spec["observation"]["failureMaximumIterations"]:
                sleeper(spec["observation"]["intervalSeconds"])
        if not evidence["faultObserved"]:
            raise P1Error("controlled Platform failure was not observed")

        latest = raw(shared_client, shared_config, "get", target_uri, runner=runner)
        if (
            latest.get("metadata", {}).get("uid") != baseline_uid
            or canonical_digest(latest.get("spec", {})) != canonical_digest(changed_spec)
        ):
            raise P1Error("Application drift before restore")
        restore_fence = now()
        restored = raw(
            shared_client,
            shared_config,
            "replace",
            target_uri,
            safe_replace_document(latest, baseline_spec),
            runner,
        )
        if (
            restored.get("metadata", {}).get("uid") != baseline_uid
            or canonical_digest(restored.get("spec", {}))
            != spec["target"]["baselineSpecDigest"]
        ):
            raise P1Error("restore optimistic-concurrency postcondition failed")
        evidence["restoreWritten"] = True

        for iteration in range(1, spec["observation"]["recoveryMaximumIterations"] + 1):
            recovered = read_state(spec, bound_clients, runner)
            applications = recovered["applications"]
            dashboards = applications["dashboards"]
            dashboard_fresh = SEMANTICS.application_ready(
                dashboards,
                expected_revision=spec["fixture"]["sourceRevision"],
                expected_path=SEMANTICS.APPLICATION_PATHS[
                    dashboards["metadata"]["name"]
                ],
                minimum_reconciled_at=restore_fence,
            )
            if (
                canonical_digest(dashboards.get("spec", {}))
                == spec["target"]["baselineSpecDigest"]
                and SEMANTICS.platform_ready(
                    list(applications.values()),
                    expected_revision=spec["fixture"]["sourceRevision"],
                )
                and dashboard_fresh
                and canonical_digest(recovered["protected"].get("data", {}))
                == spec["protectedTarget"]["dataDigest"]
            ):
                evidence["recoveryObserved"] = True
                evidence["recoveryObservationIteration"] = iteration
                evidence["PlatformReadyAfterRestore"] = True
                evidence["protectedTargetUnchanged"] = True
                break
            if iteration < spec["observation"]["recoveryMaximumIterations"]:
                sleeper(spec["observation"]["intervalSeconds"])
        if not evidence["recoveryObserved"]:
            raise P1Error("Platform recovery did not converge")

        evidence["state"] = "PASS-FAIL-CLOSED-RESTORED"
        evidence["finishedAt"] = now()
        write_exclusive(output, evidence)
        return {
            "state": evidence["state"],
            "evidenceDigest": digest(output),
            "PlatformReadyDuringFault": False,
            "PlatformReadyAfterRestore": True,
        }
    except Exception as error:
        evidence["state"] = "STOP-PRESERVE-NO-RETRY"
        evidence["failureClass"] = type(error).__name__
        evidence["finishedAt"] = now()
        if fault_written and baseline is not None and not evidence["restoreWritten"]:
            try:
                latest = raw(shared_client, shared_config, "get", target_uri, runner=runner)
                expected_fault = fault_spec(
                    baseline["spec"],
                    spec["fault"]["baselinePath"],
                    spec["fault"]["injectedPath"],
                )
                if (
                    latest.get("metadata", {}).get("uid")
                    != baseline.get("metadata", {}).get("uid")
                    or canonical_digest(latest.get("spec", {}))
                    != canonical_digest(expected_fault)
                ):
                    raise P1Error("unsafe automatic restore precondition")
                restored = raw(
                    shared_client,
                    shared_config,
                    "replace",
                    target_uri,
                    safe_replace_document(latest, baseline["spec"]),
                    runner,
                )
                if (
                    restored.get("metadata", {}).get("uid")
                    != baseline.get("metadata", {}).get("uid")
                    or canonical_digest(restored.get("spec", {}))
                    != spec["target"]["baselineSpecDigest"]
                ):
                    raise P1Error("automatic exact restore postcondition failed")
                evidence["restoreWritten"] = True
                evidence["state"] = "STOP-EXACT-RESTORE-WRITTEN-NO-RETRY"
                evidence["manualRestoreRequired"] = False
            except Exception:
                evidence["manualRestoreRequired"] = True
        if not output.exists():
            write_exclusive(output, evidence)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "preflight", "execute"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            validate_candidate(args.candidate.resolve())
            print(digest(args.candidate.resolve()))
        elif args.command == "preflight":
            print(json.dumps(preflight(args.candidate.resolve()), sort_keys=True))
        else:
            if args.grant is None or not args.execute:
                raise P1Error("execute requires --grant and --execute")
            print(
                json.dumps(
                    execute(args.candidate.resolve(), args.grant.resolve()),
                    sort_keys=True,
                )
            )
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
