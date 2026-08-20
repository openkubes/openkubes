import datetime as dt
import importlib.util
from pathlib import Path

import pytest
import yaml


HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "bounded_enablement_failure_e1_v1.py"
SPEC = importlib.util.spec_from_file_location("e1", SCRIPT)
E1 = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(E1)


def current_condition(name: str, generation: int = 1) -> dict:
    return {"type": name, "status": "True", "observedGeneration": generation}


def hcp() -> dict:
    return {
        "metadata": {
            "name": "disposable-ok141-cilium",
            "namespace": "disposable-ok141",
            "uid": "uid-1",
            "resourceVersion": "1",
            "generation": 1,
        },
        "spec": {"version": "1.19.6", "chartName": "cilium"},
        "status": {
            "conditions": [
                current_condition("Ready"),
                current_condition("HelmReleaseProxySpecsUpToDate"),
                current_condition("HelmReleaseProxiesReady"),
            ]
        },
    }


def test_fault_changes_only_version():
    baseline = hcp()["spec"]
    fault = E1.fault_spec(baseline, "1.19.6", "0.0.0-ok141-controlled-failure")
    assert fault == {"version": "0.0.0-ok141-controlled-failure", "chartName": "cilium"}
    assert baseline["version"] == "1.19.6"


def test_fault_rejects_wrong_baseline():
    with pytest.raises(E1.E1Error):
        E1.fault_spec({"version": "other"}, "1.19.6", "invalid")


def test_replace_document_preserves_concurrency_and_removes_status():
    value = hcp()
    payload = yaml.safe_load(E1.safe_replace_document(value, {"version": "invalid"}))
    assert payload["metadata"]["uid"] == "uid-1"
    assert payload["metadata"]["resourceVersion"] == "1"
    assert payload["spec"] == {"version": "invalid"}
    assert "status" not in payload


def test_mechanism_observation_accepts_current_hcp_or_projected_hrp():
    changed = hcp()
    changed["metadata"]["generation"] = 2
    changed["status"]["conditions"][0]["observedGeneration"] = 2
    assert E1.mechanism_observed_fault(changed, [], "invalid")
    changed["status"] = {}
    assert E1.mechanism_observed_fault(changed, [{"spec": {"version": "invalid"}}], "invalid")


def test_runtime_requires_two_ready_nodes_and_current_cilium():
    nodes = {
        "items": [
            {"status": {"conditions": [{"type": "Ready", "status": "True"}]}},
            {"status": {"conditions": [{"type": "Ready", "status": "True"}]}},
        ]
    }
    daemonset = {
        "metadata": {"generation": 1},
        "status": {
            "observedGeneration": 1,
            "desiredNumberScheduled": 2,
            "updatedNumberScheduled": 2,
            "numberAvailable": 2,
            "numberReady": 2,
        },
    }
    assert E1.runtime_ready(nodes, daemonset)
    nodes["items"][0]["status"]["conditions"][0]["status"] = "False"
    assert not E1.runtime_ready(nodes, daemonset)


def test_grant_template_cannot_authorize_execution(tmp_path: Path):
    template = yaml.safe_load((HERE / "enablement-e1-grant-v1.template.yaml").read_text())
    assert template["spec"]["decision"] == "NOT-GRANTED"
    assert not any(
        value
        for key, value in template["spec"].items()
        if key.endswith("Granted")
    )


def test_expired_or_overlong_grant_is_rejected(monkeypatch, tmp_path: Path):
    candidate = {"spec": {}}
    monkeypatch.setattr(E1, "validate_candidate", lambda _: candidate)
    monkeypatch.setattr(E1, "digest", lambda _: "sha256:candidate")
    grant = {
        "kind": "ControlledEnablementFailureGrant",
        "spec": {
            "decision": "GO",
            "candidateDigest": "sha256:candidate",
            "authority": "github:arashkaffamanesh",
            "singleRun": True,
            "consumed": False,
            "issuedAt": "2026-08-20T10:00:00Z",
            "expiresAt": "2026-08-20T11:00:00Z",
            "managementCredentialUseGranted": True,
            "workloadCredentialUseGranted": True,
            "failureInjectionGranted": True,
            "boundedObservationGranted": True,
            "exactRestoreGranted": True,
            "deleteGranted": False,
            "retryGranted": False,
            "generalCleanupGranted": False,
            "outageGranted": False,
            "evidencePublicationGranted": False,
        },
    }
    path = tmp_path / "grant.yaml"
    path.write_text(yaml.safe_dump(grant))
    with pytest.raises(E1.E1Error):
        E1.validate_grant(
            HERE / "candidate.yaml",
            path,
            current=dt.datetime(2026, 8, 20, 10, 30, tzinfo=dt.timezone.utc),
        )
