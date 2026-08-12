from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("controlled_m0a_execution_v3", ROOT / "controlled_m0a_execution_v3.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)

CANDIDATE = ROOT / "m0a-execution-candidate-v3.yaml"
DIGEST = ROOT / "m0a-execution-candidate-v3.sha256"
PREFLIGHT = ROOT / "m0a-v3-live-preflight-v1.yaml"
PREFLIGHT_DIGEST = ROOT / "m0a-v3-live-preflight-v1.sha256"


def valid_grant() -> dict:
    return {
        "apiVersion": "authorization.openkubes.io/v1alpha1",
        "kind": "CombinedGateGrant",
        "metadata": {"name": "test", "ticket": "OK-141"},
        "spec": {
            "version": "ok141-m0a-combined-grant/v3",
            "candidateDigest": MODULE.sha(CANDIDATE),
            "authority": "github:arashkaffamanesh",
            "decision": "GO",
            "mutationAuthorized": True,
            "credentialGrant": {"gate": "M0A-C1-v3", "granted": True, "grantID": "credential-v3"},
            "admissionGrant": {"gate": "M0A-A1-v3", "granted": True, "grantID": "admission-v3"},
            "installationGrant": {"gate": "M0a-I-v3", "granted": True, "grantID": "installation-v3"},
            "validFrom": "2026-08-12T15:00:00Z",
            "validUntil": "2026-08-12T18:00:00Z",
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
    assert document["spec"]["authorization"]["retryGranted"] is False


def test_live_preflight_is_pinned_and_non_authorizing() -> None:
    preflight = yaml.safe_load(PREFLIGHT.read_text())["spec"]
    assert MODULE.sha(PREFLIGHT) == PREFLIGHT_DIGEST.read_text().strip()
    assert preflight["candidateDigest"] == MODULE.sha(CANDIDATE)
    assert preflight["result"] == "PASS"
    assert preflight["mutationPerformed"] is False
    assert preflight["authorization"]["decision"] == "NO-GO"
    assert not any(value for key, value in preflight["authorization"].items() if key != "decision")


def test_exact_grant_verifies_only_in_its_window(tmp_path: Path) -> None:
    path = write(tmp_path, "grant.yaml", valid_grant())
    result = MODULE.verify_grant(CANDIDATE, path, datetime(2026, 8, 12, 16, 0, tzinfo=timezone.utc))
    assert result["maximumRuns"] == 1
    with pytest.raises(MODULE.ExecutionError, match="outside"):
        MODULE.verify_grant(CANDIDATE, path, datetime(2026, 8, 12, 19, 0, tzinfo=timezone.utc))


def test_grant_requires_three_distinct_ids(tmp_path: Path) -> None:
    grant = valid_grant()
    grant["spec"]["admissionGrant"]["grantID"] = "credential-v3"
    with pytest.raises(MODULE.ExecutionError, match="three distinct"):
        MODULE.verify_grant(CANDIDATE, write(tmp_path, "grant.yaml", grant), datetime(2026, 8, 12, 16, 0, tzinfo=timezone.utc))


def test_template_grants_no_authority() -> None:
    template = yaml.safe_load((ROOT / "m0a-combined-grant-v3.template.yaml").read_text())["spec"]
    assert template["candidateDigest"] == MODULE.sha(CANDIDATE)
    assert template["decision"] == "NO-GO"
    assert template["mutationAuthorized"] is False
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


def test_authorization_probe_addresses_token_subresource(monkeypatch: pytest.MonkeyPatch) -> None:
    reviewed = type("Reviewed", (), {"documents": []})()
    calls = []

    def can_i(*args, **kwargs):
        calls.append((args, kwargs))
        return False

    monkeypatch.setattr(MODULE, "auth_can_i", can_i)
    denied = subprocess.CompletedProcess([], 1, b"", b"OK-141 M0a v2 permits only exact identities")
    monkeypatch.setattr(MODULE, "kubectl", lambda *args, **kwargs: denied)
    result = MODULE.authorization_probes(Path("unused"), reviewed)
    assert result["tokenRequestSubresourceDenied"] is True
    assert any(
        args[1:3] == ("create", "serviceaccounts")
        and kwargs.get("subresource") == "token"
        and kwargs.get("namespace") == MODULE.SA_NAMESPACE
        for args, kwargs in calls
    )


def test_expiry_poll_accepts_observed_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    denied = subprocess.CompletedProcess([], 1, b"", b"Unauthorized")
    monkeypatch.setattr(MODULE, "kubectl", lambda *args, **kwargs: denied)
    result = MODULE.poll_token_rejection_until_expiry(Path("unused"), datetime.now(timezone.utc) + timedelta(seconds=5), 30)
    assert result["tokenRejected"] is True


def test_expiry_poll_accepts_anonymous_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"status": {"userInfo": {"username": "system:anonymous"}}}
    observed = subprocess.CompletedProcess([], 0, json.dumps(body).encode(), b"")
    monkeypatch.setattr(MODULE, "kubectl", lambda *args, **kwargs: observed)
    result = MODULE.poll_token_rejection_until_expiry(Path("unused"), datetime.now(timezone.utc) + timedelta(seconds=5), 30)
    assert result["tokenRejected"] is True
    assert result["fallbackIdentity"] == "system:anonymous"


def test_candidate_tampering_fails_closed(tmp_path: Path) -> None:
    document = copy.deepcopy(yaml.safe_load(CANDIDATE.read_text()))
    document["spec"]["authorization"]["retryGranted"] = True
    with pytest.raises(MODULE.ExecutionError):
        MODULE.verify_candidate(write(tmp_path, "candidate.yaml", document))
