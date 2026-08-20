#!/usr/bin/env python3
"""Bounded E1 Enablement failure, observation, and exact restoration."""

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
CANDIDATE = HERE / "enablement-e1-execution-candidate-v1.yaml"
SEMANTICS_PATH = HERE / "controlled_failure_semantics_v1.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


SEMANTICS = load_module("ok141_controlled_failure_semantics", SEMANTICS_PATH)


class E1Error(RuntimeError):
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
        raise E1Error("timestamp lacks timezone")
    return parsed.astimezone(dt.timezone.utc)


def read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise E1Error(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise E1Error(f"{context}: expected {expected!r}, got {actual!r}")


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = read_yaml(path)
    expect(value.get("kind"), "ControlledEnablementFailureExecutionCandidate", "kind")
    spec = value["spec"]
    expect(spec["state"], "PREPARED-NO-GO", "state")
    expect(
        digest(HERE / "enablement-failure-candidate-v1.yaml"),
        spec["sourceCandidateDigest"],
        "source candidate",
    )
    expect(digest(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool")
    expect(digest(SEMANTICS_PATH), spec["semanticsDigest"], "semantics")
    expect(spec["target"]["name"], "disposable-ok141-cilium", "target name")
    expect(spec["fault"]["baselineVersion"], "1.19.6", "baseline version")
    expect(
        spec["fault"]["injectedVersion"],
        "0.0.0-ok141-controlled-failure",
        "fault version",
    )
    authorization = spec["authorization"]
    expect(authorization["decision"], "NO-GO", "authorization")
    if any(value for key, value in authorization.items() if key.endswith("Granted")):
        raise E1Error("candidate grants live authority")
    return value


def validate_grant(
    candidate_path: Path,
    grant_path: Path,
    current: dt.datetime | None = None,
) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant = read_yaml(grant_path)
    expect(grant.get("kind"), "ControlledEnablementFailureGrant", "grant kind")
    spec = grant["spec"]
    expect(spec["decision"], "GO", "grant decision")
    expect(spec["candidateDigest"], digest(candidate_path), "candidate digest")
    expect(spec["authority"], "github:arashkaffamanesh", "authority")
    required = (
        "managementCredentialUseGranted",
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
        raise E1Error("grant lacks required authority")
    if any(spec.get(key) is not False for key in forbidden):
        raise E1Error("grant expands forbidden authority")
    if spec.get("singleRun") is not True or spec.get("consumed") is not False:
        raise E1Error("grant is not an unused single run")
    point = current or dt.datetime.now(dt.timezone.utc)
    issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= point <= expires or expires - issued > dt.timedelta(minutes=45):
        raise E1Error("grant inactive or exceeds 45 minutes")
    return grant


def safe_replace_document(current: dict[str, Any], new_spec: dict[str, Any]) -> bytes:
    metadata = current.get("metadata", {})
    if not metadata.get("uid") or not metadata.get("resourceVersion"):
        raise E1Error("object lacks UID/resourceVersion")
    result = copy.deepcopy(current)
    result.pop("status", None)
    result["metadata"].pop("managedFields", None)
    result["metadata"].pop("selfLink", None)
    result["spec"] = copy.deepcopy(new_spec)
    return json.dumps(result, sort_keys=True, separators=(",", ":")).encode()


def fault_spec(baseline: dict[str, Any], baseline_version: str, injected: str) -> dict[str, Any]:
    if baseline.get("version") != baseline_version:
        raise E1Error("baseline version precondition failed")
    result = copy.deepcopy(baseline)
    result["version"] = injected
    return result


def conditions_current_true(obj: dict[str, Any], names: tuple[str, ...]) -> bool:
    generation = obj.get("metadata", {}).get("generation")
    conditions = {
        item.get("type"): item for item in obj.get("status", {}).get("conditions", [])
    }
    return isinstance(generation, int) and all(
        conditions.get(name, {}).get("status") == "True"
        and conditions.get(name, {}).get("observedGeneration") == generation
        for name in names
    )


def mechanism_observed_fault(hcp: dict[str, Any], hrps: list[dict[str, Any]], injected: str) -> bool:
    generation = hcp.get("metadata", {}).get("generation")
    observed = hcp.get("status", {}).get("observedGeneration") == generation or any(
        condition.get("observedGeneration") == generation
        for condition in hcp.get("status", {}).get("conditions", [])
    )
    projected = len(hrps) == 1 and hrps[0].get("spec", {}).get("version") == injected
    return bool(observed or projected)


def runtime_ready(nodes: dict[str, Any], daemonset: dict[str, Any]) -> bool:
    items = nodes.get("items", [])
    if len(items) != 2:
        return False
    for node in items:
        condition = next(
            (
                item
                for item in node.get("status", {}).get("conditions", [])
                if item.get("type") == "Ready"
            ),
            {},
        )
        if condition.get("status") != "True":
            return False
    status = daemonset.get("status", {})
    return (
        status.get("observedGeneration") == daemonset.get("metadata", {}).get("generation")
        and all(
            status.get(field) == 2
            for field in (
                "desiredNumberScheduled",
                "updatedNumberScheduled",
                "numberAvailable",
                "numberReady",
            )
        )
    )


def raw_get(
    client: Path,
    kubeconfig: Path,
    uri: str,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    result = runner(
        [str(client), "--kubeconfig", str(kubeconfig), "get", "--raw", uri],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise E1Error("bounded raw GET failed")
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise E1Error("bounded raw GET returned non-object")
    return value


def raw_replace(
    client: Path,
    kubeconfig: Path,
    uri: str,
    payload: bytes,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    result = runner(
        [
            str(client),
            "--kubeconfig",
            str(kubeconfig),
            "replace",
            "--raw",
            uri,
            "--filename",
            "-",
        ],
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise E1Error("bounded raw replace failed")
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise E1Error("bounded raw replace returned non-object")
    return value


def check_tools_and_credentials(spec: dict[str, Any]) -> tuple[Path, Path, Path, Path]:
    management_client = Path(spec["management"]["clientPath"])
    workload_client = Path(spec["workload"]["clientPath"])
    management_kubeconfig = Path(spec["management"]["kubeconfigPath"])
    workload_kubeconfig = Path(spec["workload"]["kubeconfigPath"])
    for path, expected in (
        (management_client, spec["management"]["clientDigest"]),
        (workload_client, spec["workload"]["clientDigest"]),
    ):
        if not path.is_file() or digest(path) != expected:
            raise E1Error("kubectl identity mismatch")
    for path in (management_kubeconfig, workload_kubeconfig):
        if path.is_symlink() or not path.is_file() or (path.stat().st_mode & 0o777) != 0o600:
            raise E1Error("unsafe kubeconfig")
    return management_client, workload_client, management_kubeconfig, workload_kubeconfig


def read_state(
    spec: dict[str, Any],
    management_client: Path,
    workload_client: Path,
    management_kubeconfig: Path,
    workload_kubeconfig: Path,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    queries = spec["queries"]
    hcp = raw_get(management_client, management_kubeconfig, queries["hcp"], runner)
    hrps = raw_get(management_client, management_kubeconfig, queries["hrps"], runner).get("items", [])
    nodes = raw_get(workload_client, workload_kubeconfig, queries["nodes"], runner)
    daemonset = raw_get(
        workload_client, workload_kubeconfig, queries["ciliumDaemonSet"], runner
    )
    return {"hcp": hcp, "hrps": hrps, "nodes": nodes, "daemonset": daemonset}


def preflight(candidate_path: Path, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    spec = candidate["spec"]
    clients = check_tools_and_credentials(spec)
    state = read_state(spec, *clients, runner)
    hcp, hrps = state["hcp"], state["hrps"]
    target = spec["target"]
    expect(hcp.get("metadata", {}).get("name"), target["name"], "HCP name")
    expect(hcp.get("metadata", {}).get("namespace"), target["namespace"], "HCP namespace")
    expect(canonical_digest(hcp.get("spec", {})), target["baselineSpecDigest"], "HCP spec")
    annotations = hcp.get("metadata", {}).get("annotations", {})
    fixture = spec["fixture"]
    for key, expected in (
        ("openkubes.io/intent-revision", fixture["R"]),
        ("openkubes.io/enablement-revision", fixture["E"]),
        ("openkubes.io/execution-fixture", fixture["fixtureDigest"]),
    ):
        expect(annotations.get(key), expected, key)
    if len(hrps) != 1:
        raise E1Error("expected exactly one HRP")
    if not conditions_current_true(
        hcp,
        ("Ready", "HelmReleaseProxySpecsUpToDate", "HelmReleaseProxiesReady"),
    ):
        raise E1Error("HCP baseline is not current and ready")
    if not conditions_current_true(hrps[0], ("Ready", "HelmReleaseReady")):
        raise E1Error("HRP baseline is not current and ready")
    if not runtime_ready(state["nodes"], state["daemonset"]):
        raise E1Error("workload runtime baseline is not ready")
    if not SEMANTICS.network_ready(hcp, hrps, runtime_ready=True):
        raise E1Error("NetworkReady baseline is false")
    return {
        "state": "PASS-READY-NO-WRITES",
        "hcpGeneration": hcp["metadata"]["generation"],
        "hcpUIDDigest": sha_bytes(hcp["metadata"]["uid"].encode()),
        "hrpCount": 1,
        "NetworkReady": True,
        "runtimeReady": True,
    }


def write_exclusive(path: Path, value: dict[str, Any]) -> None:
    data = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)


def execute(
    candidate_path: Path,
    grant_path: Path,
    runner: Callable[..., Any] = subprocess.run,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant = validate_grant(candidate_path, grant_path)
    spec, grant_spec = candidate["spec"], grant["spec"]
    management_client, workload_client, management_kubeconfig, workload_kubeconfig = check_tools_and_credentials(spec)
    output = Path(grant_spec["outputPath"])
    if output.exists():
        raise E1Error("exclusive evidence output already exists")
    evidence: dict[str, Any] = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "ControlledEnablementFailureEvidence",
        "candidateDigest": digest(candidate_path),
        "grantID": grant_spec["grantID"],
        "startedAt": now(),
        "state": "STARTED",
        "faultWritten": False,
        "faultObserved": False,
        "restoreWritten": False,
        "recoveryObserved": False,
        "runnerRepairPerformed": False,
        "directRuntimeMutationPerformed": False,
        "deletePerformed": False,
        "retryPerformed": False,
        "rawObjectsRetained": False,
        "credentialPayloadRetained": False,
    }
    fault_written = False
    baseline: dict[str, Any] | None = None
    hcp_uri = spec["queries"]["hcp"]
    try:
        preflight_state = preflight(candidate_path, runner)
        evidence["preflight"] = preflight_state
        baseline = raw_get(management_client, management_kubeconfig, hcp_uri, runner)
        baseline_uid = baseline["metadata"]["uid"]
        baseline_spec = copy.deepcopy(baseline["spec"])
        fault = fault_spec(
            baseline_spec,
            spec["fault"]["baselineVersion"],
            spec["fault"]["injectedVersion"],
        )
        changed = raw_replace(
            management_client,
            management_kubeconfig,
            hcp_uri,
            safe_replace_document(baseline, fault),
            runner,
        )
        if (
            changed.get("metadata", {}).get("uid") != baseline_uid
            or changed.get("metadata", {}).get("resourceVersion")
            == baseline.get("metadata", {}).get("resourceVersion")
            or changed.get("spec", {}).get("version") != spec["fault"]["injectedVersion"]
        ):
            raise E1Error("fault optimistic-concurrency postcondition failed")
        fault_written = True
        evidence["faultWritten"] = True
        evidence["faultGeneration"] = changed["metadata"]["generation"]

        observed_state = None
        for iteration in range(1, spec["observation"]["failureMaximumIterations"] + 1):
            observed_state = read_state(
                spec,
                management_client,
                workload_client,
                management_kubeconfig,
                workload_kubeconfig,
                runner,
            )
            observed_hcp, observed_hrps = observed_state["hcp"], observed_state["hrps"]
            evaluator_ready = SEMANTICS.network_ready(
                observed_hcp, observed_hrps, runtime_ready=True
            )
            if (
                not evaluator_ready
                and mechanism_observed_fault(
                    observed_hcp, observed_hrps, spec["fault"]["injectedVersion"]
                )
                and runtime_ready(observed_state["nodes"], observed_state["daemonset"])
            ):
                evidence["faultObserved"] = True
                evidence["failureObservationIteration"] = iteration
                evidence["NetworkReadyDuringFault"] = False
                evidence["runtimeReadyDuringFault"] = True
                break
            if iteration < spec["observation"]["failureMaximumIterations"]:
                sleeper(spec["observation"]["intervalSeconds"])
        if not evidence["faultObserved"]:
            raise E1Error("controlled Enablement failure was not observed")

        latest = raw_get(management_client, management_kubeconfig, hcp_uri, runner)
        if latest.get("metadata", {}).get("uid") != baseline_uid:
            raise E1Error("HCP UID drift before restore")
        latest_spec = latest.get("spec", {})
        expected_fault = fault_spec(
            baseline_spec,
            spec["fault"]["baselineVersion"],
            spec["fault"]["injectedVersion"],
        )
        if canonical_digest(latest_spec) != canonical_digest(expected_fault):
            raise E1Error("HCP spec drift before restore")
        restored = raw_replace(
            management_client,
            management_kubeconfig,
            hcp_uri,
            safe_replace_document(latest, baseline_spec),
            runner,
        )
        if (
            restored.get("metadata", {}).get("uid") != baseline_uid
            or canonical_digest(restored.get("spec", {})) != spec["target"]["baselineSpecDigest"]
        ):
            raise E1Error("restore optimistic-concurrency postcondition failed")
        evidence["restoreWritten"] = True

        for iteration in range(1, spec["observation"]["recoveryMaximumIterations"] + 1):
            recovered = read_state(
                spec,
                management_client,
                workload_client,
                management_kubeconfig,
                workload_kubeconfig,
                runner,
            )
            if (
                canonical_digest(recovered["hcp"].get("spec", {}))
                == spec["target"]["baselineSpecDigest"]
                and SEMANTICS.network_ready(
                    recovered["hcp"],
                    recovered["hrps"],
                    runtime_ready=runtime_ready(recovered["nodes"], recovered["daemonset"]),
                )
            ):
                evidence["recoveryObserved"] = True
                evidence["recoveryObservationIteration"] = iteration
                evidence["NetworkReadyAfterRestore"] = True
                evidence["runtimeReadyAfterRestore"] = True
                break
            if iteration < spec["observation"]["recoveryMaximumIterations"]:
                sleeper(spec["observation"]["intervalSeconds"])
        if not evidence["recoveryObserved"]:
            raise E1Error("Enablement recovery did not converge")

        evidence["state"] = "PASS-FAIL-CLOSED-RESTORED"
        evidence["finishedAt"] = now()
        write_exclusive(output, evidence)
        return {
            "state": evidence["state"],
            "evidenceDigest": digest(output),
            "NetworkReadyDuringFault": False,
            "NetworkReadyAfterRestore": True,
        }
    except Exception as error:
        evidence["state"] = "STOP-PRESERVE-NO-RETRY"
        evidence["failureClass"] = type(error).__name__
        evidence["finishedAt"] = now()
        if fault_written and baseline is not None and not evidence["restoreWritten"]:
            try:
                latest = raw_get(
                    management_client, management_kubeconfig, hcp_uri, runner
                )
                expected_fault = fault_spec(
                    baseline["spec"],
                    spec["fault"]["baselineVersion"],
                    spec["fault"]["injectedVersion"],
                )
                if (
                    latest.get("metadata", {}).get("uid")
                    != baseline.get("metadata", {}).get("uid")
                    or canonical_digest(latest.get("spec", {}))
                    != canonical_digest(expected_fault)
                ):
                    raise E1Error("unsafe automatic restore precondition")
                restored = raw_replace(
                    management_client,
                    management_kubeconfig,
                    hcp_uri,
                    safe_replace_document(latest, baseline["spec"]),
                    runner,
                )
                if (
                    restored.get("metadata", {}).get("uid")
                    != baseline.get("metadata", {}).get("uid")
                    or canonical_digest(restored.get("spec", {}))
                    != spec["target"]["baselineSpecDigest"]
                ):
                    raise E1Error("automatic restore postcondition failed")
                evidence["restoreWritten"] = True
                evidence["state"] = "STOP-EXACT-RESTORE-WRITTEN-NO-RETRY"
                evidence["manualRestoreRequired"] = False
            except Exception:
                evidence["manualRestoreRequired"] = True
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
                raise E1Error("execute requires --grant and --execute")
            print(
                json.dumps(
                    execute(args.candidate.resolve(), args.grant.resolve()), sort_keys=True
                )
            )
        return 0
    except (E1Error, KeyError, OSError, TypeError, ValueError, yaml.YAMLError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
