from __future__ import annotations

import ast
import copy
import importlib.util
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("controlled_m0a_execution_v4", ROOT / "controlled_m0a_execution_v4.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)

CANDIDATE = ROOT / "m0a-execution-candidate-v4.yaml"
DIGEST = ROOT / "m0a-execution-candidate-v4.sha256"
PREFLIGHT = ROOT / "m0a-v4-live-preflight-v1.yaml"
PREFLIGHT_DIGEST = ROOT / "m0a-v4-live-preflight-v1.sha256"


def valid_grant() -> dict:
    return {
        "apiVersion": "authorization.openkubes.io/v1alpha1",
        "kind": "CombinedGateGrant",
        "metadata": {"name": "test", "ticket": "OK-141"},
        "spec": {
            "version": "ok141-m0a-combined-grant/v4",
            "candidateDigest": MODULE.sha(CANDIDATE),
            "authority": "github:arashkaffamanesh",
            "decision": "GO",
            "mutationAuthorized": True,
            "credentialGrant": {"gate": "M0A-C1-v4", "granted": True, "grantID": "credential-v4"},
            "admissionGrant": {"gate": "M0A-A1-v4", "granted": True, "grantID": "admission-v4"},
            "installationGrant": {"gate": "M0a-I-v4", "granted": True, "grantID": "installation-v4"},
            "validFrom": "2026-08-12T17:00:00Z",
            "validUntil": "2026-08-12T20:00:00Z",
            "maximumRuns": 1,
            "evidenceOutputPath": "/private/tmp/ok141-m0a-v4-test-evidence.json",
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
    assert document["spec"]["installation"]["submissionMethod"] == "create"
    assert document["spec"]["authorization"]["mutationAuthorized"] is False
    assert document["spec"]["authorization"]["retryGranted"] is False


def test_live_preflight_is_pinned_and_non_authorizing() -> None:
    preflight = yaml.safe_load(PREFLIGHT.read_text())["spec"]
    assert MODULE.sha(PREFLIGHT) == PREFLIGHT_DIGEST.read_text().strip()
    assert preflight["candidateDigest"] == MODULE.sha(CANDIDATE)
    assert preflight["result"] == "PASS"
    assert preflight["mutationPerformed"] is False
    assert preflight["reviewedInstallation"]["objectCount"] == 19
    assert preflight["reviewedInstallation"]["exactIdentityAbsence"] == 19
    assert preflight["lifecycleInventory"] == {"clusters": 0, "machines": 0, "machineDeployments": 0}
    assert preflight["authorization"]["decision"] == "NO-GO"
    assert not any(value for key, value in preflight["authorization"].items() if key != "decision")


def test_executor_contains_create_but_no_apply_invocation() -> None:
    tree = ast.parse((ROOT / "controlled_m0a_execution_v4.py").read_text())
    kubectl_operations = []
    for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
        if isinstance(call.func, ast.Name) and call.func.id == "kubectl" and len(call.args) >= 2 and isinstance(call.args[1], ast.List):
            first = call.args[1].elts[0] if call.args[1].elts else None
            if isinstance(first, ast.Constant):
                kubectl_operations.append(first.value)
    assert "create" in kubectl_operations
    assert "apply" not in kubectl_operations


def test_exact_grant_verifies_only_in_window(tmp_path: Path) -> None:
    path = write(tmp_path, "grant.yaml", valid_grant())
    result = MODULE.verify_grant(CANDIDATE, path, datetime(2026, 8, 12, 18, 0, tzinfo=timezone.utc))
    assert result["maximumRuns"] == 1
    assert result["evidenceOutputPath"].startswith("/private/tmp/")
    with pytest.raises(MODULE.ExecutionError, match="outside"):
        MODULE.verify_grant(CANDIDATE, path, datetime(2026, 8, 12, 21, 0, tzinfo=timezone.utc))


def test_grant_requires_three_distinct_ids(tmp_path: Path) -> None:
    grant = valid_grant()
    grant["spec"]["admissionGrant"]["grantID"] = "credential-v4"
    with pytest.raises(MODULE.ExecutionError, match="three distinct"):
        MODULE.verify_grant(CANDIDATE, write(tmp_path, "grant.yaml", grant), datetime(2026, 8, 12, 18, 0, tzinfo=timezone.utc))


def test_grant_requires_private_tmp_evidence(tmp_path: Path) -> None:
    grant = valid_grant()
    grant["spec"]["evidenceOutputPath"] = "/Users/arash/unsafe.json"
    with pytest.raises(MODULE.ExecutionError, match="/private/tmp"):
        MODULE.verify_grant(CANDIDATE, write(tmp_path, "grant.yaml", grant), datetime(2026, 8, 12, 18, 0, tzinfo=timezone.utc))


def test_template_grants_no_authority() -> None:
    template = yaml.safe_load((ROOT / "m0a-combined-grant-v4.template.yaml").read_text())["spec"]
    assert template["candidateDigest"] == MODULE.sha(CANDIDATE)
    assert template["decision"] == "NO-GO"
    assert template["mutationAuthorized"] is False
    assert template["evidenceOutputPath"] is None
    assert not any(template[key]["granted"] for key in ("credentialGrant", "admissionGrant", "installationGrant"))


def test_execute_requires_explicit_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(MODULE, "execute", lambda *args: calls.append(args))
    monkeypatch.setattr(
        "sys.argv",
        ["executor", "execute", "--candidate", str(CANDIDATE), "--grant", "missing", "--admin-kubeconfig", "missing", "--evidence-output", "missing"],
    )
    assert MODULE.main() == 2
    assert calls == []


def test_exact_inventory_records_present_and_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    reviewed = type("Reviewed", (), {"documents": [
        {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "caaph-system"}},
        {"apiVersion": "v1", "kind": "ServiceAccount", "metadata": {"name": "controller", "namespace": "caaph-system"}},
    ]})()
    live = {"metadata": {"uid": "uid-1", "resourceVersion": "7", "generation": 1}}
    responses = iter([
        subprocess.CompletedProcess([], 0, json.dumps(live).encode(), b""),
        subprocess.CompletedProcess([], 1, b"", b"Error from server (NotFound): not found"),
    ])
    monkeypatch.setattr(MODULE, "kubectl", lambda *args, **kwargs: next(responses))
    result = MODULE.exact_object_inventory(Path("unused"), reviewed)
    assert result["present"] == 1
    assert result["absent"] == 1
    assert result["objects"][0]["uid"] == "uid-1"


def test_live_preflight_requires_all_exact_identities_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    candidate, refs = MODULE.verify_candidate(CANDIDATE)
    reviewed = type("Reviewed", (), {"documents": []})()
    monkeypatch.setattr(MODULE.V2, "live_preflight", lambda *args: {"base": "pass"})
    monkeypatch.setattr(MODULE.INSTALLER, "verify_reviewed_object_set", lambda *args: reviewed)
    monkeypatch.setattr(MODULE, "exact_object_inventory", lambda *args: {"expected": 19, "present": 0, "absent": 19, "objects": []})
    result = MODULE.live_preflight(candidate, refs, Path("unused"))
    assert result["exactIdentityAbsence"] == 19


def test_live_preflight_fails_when_one_exact_identity_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    candidate, refs = MODULE.verify_candidate(CANDIDATE)
    reviewed = type("Reviewed", (), {"documents": []})()
    monkeypatch.setattr(MODULE.V2, "live_preflight", lambda *args: {})
    monkeypatch.setattr(MODULE.INSTALLER, "verify_reviewed_object_set", lambda *args: reviewed)
    monkeypatch.setattr(MODULE, "exact_object_inventory", lambda *args: {"expected": 19, "present": 1, "absent": 18, "objects": []})
    with pytest.raises(MODULE.ExecutionError, match="existing identity"):
        MODULE.live_preflight(candidate, refs, Path("unused"))


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("spec", "authorization", "retryGranted"), True),
        (("spec", "installation", "serverSideApplyAllowed"), True),
        (("spec", "installation", "automaticRollbackAllowed"), True),
        (("spec", "installation", "maximumSubmissions"), 2),
        (("spec", "credential", "rejectionDeadlineOffsetSeconds"), 30),
    ],
)
def test_candidate_tampering_fails_closed(tmp_path: Path, path: tuple[str, ...], value) -> None:
    document = copy.deepcopy(yaml.safe_load(CANDIDATE.read_text()))
    cursor = document
    for segment in path[:-1]:
        cursor = cursor[segment]
    cursor[path[-1]] = value
    with pytest.raises(MODULE.ExecutionError):
        MODULE.verify_candidate(write(tmp_path, "candidate.yaml", document))
