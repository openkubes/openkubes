from __future__ import annotations

import copy
import importlib.util
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("controlled_m0a_execution_v2", ROOT / "controlled_m0a_execution_v2.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)

CANDIDATE = ROOT / "m0a-execution-candidate-v2.yaml"
DIGEST = ROOT / "m0a-execution-candidate-v2.sha256"
PREFLIGHT = ROOT / "m0a-v2-live-preflight-v1.yaml"
PREFLIGHT_DIGEST = ROOT / "m0a-v2-live-preflight-v1.sha256"


def valid_grant() -> dict:
    return {
        "apiVersion": "authorization.openkubes.io/v1alpha1",
        "kind": "CombinedGateGrant",
        "metadata": {"name": "test", "ticket": "OK-141"},
        "spec": {
            "version": "ok141-m0a-combined-grant/v2",
            "candidateDigest": MODULE.sha(CANDIDATE),
            "authority": "github:arashkaffamanesh",
            "decision": "GO",
            "mutationAuthorized": True,
            "credentialGrant": {"gate": "M0A-C1-v2", "granted": True, "grantID": "credential-1"},
            "admissionGrant": {"gate": "M0A-A1-v2", "granted": True, "grantID": "admission-1"},
            "installationGrant": {"gate": "M0a-I-v2", "granted": True, "grantID": "installation-1"},
            "validFrom": "2026-08-12T11:00:00Z",
            "validUntil": "2026-08-12T14:00:00Z",
            "maximumRuns": 1,
            "rollbackGranted": False,
            "targetConvergenceGranted": False,
            "m0bInstallationGranted": False,
            "go1Granted": False,
            "evidencePublicationGranted": False,
            "failureInjectionGranted": False,
        },
    }


def write(tmp_path: Path, name: str, value: dict) -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(value, sort_keys=False))
    return path


def test_candidate_and_digest_verify_without_authority() -> None:
    document, _ = MODULE.verify_candidate(CANDIDATE)
    assert MODULE.sha(CANDIDATE) == DIGEST.read_text().strip()
    assert document["spec"]["authorization"]["mutationAuthorized"] is False


def test_live_preflight_is_pinned_and_non_authorizing() -> None:
    preflight = yaml.safe_load(PREFLIGHT.read_text())["spec"]
    assert MODULE.sha(PREFLIGHT) == PREFLIGHT_DIGEST.read_text().strip()
    assert preflight["candidateDigest"] == MODULE.sha(CANDIDATE)
    assert preflight["result"] == "PASS"
    assert preflight["mutationPerformed"] is False
    assert preflight["authorization"]["decision"] == "NO-GO"
    assert not any(value for key, value in preflight["authorization"].items() if key != "decision")


def test_grant_requires_three_distinct_ids(tmp_path: Path) -> None:
    grant = valid_grant()
    grant["spec"]["admissionGrant"]["grantID"] = "credential-1"
    with pytest.raises(MODULE.ExecutionError, match="three distinct"):
        MODULE.verify_grant(CANDIDATE, write(tmp_path, "grant.yaml", grant), datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc))


def test_exact_grant_verifies_in_its_window(tmp_path: Path) -> None:
    result = MODULE.verify_grant(CANDIDATE, write(tmp_path, "grant.yaml", valid_grant()), datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc))
    assert result["maximumRuns"] == 1


def test_template_grants_no_authority() -> None:
    template = yaml.safe_load((ROOT / "m0a-combined-grant-v2.template.yaml").read_text())["spec"]
    assert template["decision"] == "NO-GO"
    assert template["mutationAuthorized"] is False
    assert not any(template[key]["granted"] for key in ("credentialGrant", "admissionGrant", "installationGrant"))


def test_execute_requires_explicit_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(MODULE, "execute", lambda *args: calls.append(args))
    monkeypatch.setattr("sys.argv", ["executor", "execute", "--candidate", str(CANDIDATE), "--grant", "missing", "--admin-kubeconfig", "missing", "--evidence-output", "missing"])
    assert MODULE.main() == 2
    assert calls == []


def test_wrong_name_admission_probe_must_be_policy_denial(monkeypatch: pytest.MonkeyPatch) -> None:
    reviewed = type("Reviewed", (), {"documents": []})()
    monkeypatch.setattr(MODULE, "auth_can_i", lambda *args, **kwargs: False)
    denied = subprocess.CompletedProcess([], 1, b"", b"generic denial")
    monkeypatch.setattr(MODULE, "kubectl", lambda *args, **kwargs: denied)
    with pytest.raises(MODULE.ExecutionError, match="wrong-name admission"):
        MODULE.authorization_probes(Path("unused"), reviewed)


def test_cleanup_removes_authority_before_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    all_objects = {item[0]: item[0] + "-uid" for item in MODULE.BOOTSTRAP_OBJECTS}
    observations = iter((all_objects, {}))
    monkeypatch.setattr(MODULE, "discover_bootstrap_objects", lambda _: next(observations))
    commands = []
    monkeypatch.setattr(MODULE, "kubectl", lambda _config, args, **kwargs: commands.append(args))
    result = MODULE.cleanup_bootstrap(Path("unused"), all_objects)
    assert result["removed"] is True
    assert commands[0][:3] == ["delete", "clusterrolebinding", MODULE.SA_NAME]
    assert commands[1][:3] == ["delete", "serviceaccount", MODULE.SA_NAME]
    assert commands[-1][:3] == ["delete", "validatingadmissionpolicy", MODULE.POLICY_NAME]


def test_revocation_accepts_anonymous_fallback_but_not_installer_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    anonymous = {"status": {"userInfo": {"username": "system:anonymous"}}}
    completed = subprocess.CompletedProcess([], 0, json_bytes(anonymous), b"")
    monkeypatch.setattr(MODULE, "kubectl", lambda *args, **kwargs: completed)
    result = MODULE.poll_token_rejection(Path("unused"), 1)
    assert result["tokenRejected"] is True
    assert result["fallbackIdentity"] == "system:anonymous"


def json_bytes(value: dict) -> bytes:
    import json

    return json.dumps(value).encode()


def test_candidate_tampering_fails_closed(tmp_path: Path) -> None:
    document = copy.deepcopy(yaml.safe_load(CANDIDATE.read_text()))
    document["spec"]["authorization"]["mutationAuthorized"] = True
    with pytest.raises(MODULE.ExecutionError):
        MODULE.verify_candidate(write(tmp_path, "candidate.yaml", document))
