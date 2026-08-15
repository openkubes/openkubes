from __future__ import annotations

import ast
import copy
import importlib.util
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("controlled_m0a_execution_v5", ROOT / "controlled_m0a_execution_v5.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)

CANDIDATE = ROOT / "m0a-execution-candidate-v5.yaml"
DIGEST = ROOT / "m0a-execution-candidate-v5.sha256"
PREFLIGHT = ROOT / "m0a-v5-live-preflight-v1.yaml"
PREFLIGHT_DIGEST = ROOT / "m0a-v5-live-preflight-v1.sha256"


def valid_grant() -> dict:
    return {
        "apiVersion": "authorization.openkubes.io/v1alpha1",
        "kind": "CombinedGateGrant",
        "metadata": {"name": "test", "ticket": "OK-141"},
        "spec": {
            "version": "ok141-m0a-combined-grant/v5",
            "candidateDigest": MODULE.sha(CANDIDATE),
            "authority": "github:arashkaffamanesh",
            "decision": "GO",
            "mutationAuthorized": True,
            "credentialGrant": {"gate": "M0A-C1-v5", "granted": True, "grantID": "credential-v5"},
            "admissionGrant": {"gate": "M0A-A1-v5", "granted": True, "grantID": "admission-v5"},
            "installationGrant": {"gate": "M0a-I-v5", "granted": True, "grantID": "installation-v5"},
            "validFrom": "2026-08-12T19:00:00Z",
            "validUntil": "2026-08-12T22:00:00Z",
            "maximumRuns": 1,
            "evidenceOutputPath": "/private/tmp/ok141-m0a-v5-test-evidence.json",
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
    assert document["spec"]["installation"]["positiveServerDryRunRequired"] is False
    assert document["spec"]["authorization"]["mutationAuthorized"] is False


def test_live_preflight_is_toolchain_bound_and_non_authorizing() -> None:
    value = yaml.safe_load(PREFLIGHT.read_text())["spec"]
    assert MODULE.sha(PREFLIGHT) == PREFLIGHT_DIGEST.read_text().strip()
    assert value["candidateDigest"] == MODULE.sha(CANDIDATE)
    assert value["toolchain"]["digest"] == "sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf"
    assert value["reviewedInstallation"]["exactIdentityAbsence"] == 19
    assert value["mutationPerformed"] is False
    assert not any(item for key, item in value["authorization"].items() if key != "decision")


def test_executor_has_no_apply_or_server_dry_run_invocation() -> None:
    tree = ast.parse((ROOT / "controlled_m0a_execution_v5.py").read_text())
    strings = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    assert "apply" not in strings
    assert "--dry-run=server" not in strings


def test_exact_grant_verifies_only_in_window(tmp_path: Path) -> None:
    grant = write(tmp_path, "grant.yaml", valid_grant())
    result = MODULE.verify_grant(CANDIDATE, grant, datetime(2026, 8, 12, 20, 0, tzinfo=timezone.utc))
    assert result["maximumRuns"] == 1
    with pytest.raises(MODULE.ExecutionError, match="outside"):
        MODULE.verify_grant(CANDIDATE, grant, datetime(2026, 8, 12, 23, 0, tzinfo=timezone.utc))


def test_grant_requires_distinct_ids(tmp_path: Path) -> None:
    value = valid_grant()
    value["spec"]["admissionGrant"]["grantID"] = "credential-v5"
    with pytest.raises(MODULE.ExecutionError, match="distinct"):
        MODULE.verify_grant(CANDIDATE, write(tmp_path, "grant.yaml", value), datetime(2026, 8, 12, 20, 0, tzinfo=timezone.utc))


def test_template_grants_no_authority() -> None:
    template = yaml.safe_load((ROOT / "m0a-combined-grant-v5.template.yaml").read_text())["spec"]
    assert template["candidateDigest"] == MODULE.sha(CANDIDATE)
    assert template["decision"] == "NO-GO"
    assert template["mutationAuthorized"] is False
    assert template["evidenceOutputPath"] is None


def test_sanitizer_removes_paths_and_jwt() -> None:
    token = "eyJabc.def_ghi.jkl-mno"
    result = MODULE.sanitize_output(f"failed /private/tmp/tool {token}".encode(), paths=[Path("/private/tmp/tool")], maximum=4096)
    assert "/private/tmp/tool" not in result
    assert token not in result
    assert "<redacted-path>" in result
    assert "<redacted-token>" in result


def test_diagnostic_is_bounded_and_excludes_payload() -> None:
    candidate, _ = MODULE.verify_candidate(CANDIDATE)
    completed = subprocess.CompletedProcess([], 1, b"x" * 5000, b"y" * 5000)
    result = MODULE.diagnostic(completed, "create", [], candidate)
    assert len(result["stdout"]) == 4096
    assert len(result["stderr"]) == 4096
    assert result["outputTruncated"] is True
    assert result["payloadRetained"] is False


def test_post_boundary_probe_records_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    denied = subprocess.CompletedProcess([], 1, b"", b"Unauthorized")
    monkeypatch.setattr(MODULE, "kubectl", lambda *args, **kwargs: denied)
    result = MODULE.decisive_post_boundary_probe(Path("unused"), datetime.now(timezone.utc) - timedelta(seconds=101), 100)
    assert result["tokenRejected"] is True
    assert result["notBeforeBoundary"] is True


def test_post_boundary_probe_records_still_authenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"status": {"userInfo": {"username": "system:serviceaccount:openkubes-system:installer"}}}
    allowed = subprocess.CompletedProcess([], 0, json.dumps(body).encode(), b"")
    monkeypatch.setattr(MODULE, "kubectl", lambda *args, **kwargs: allowed)
    result = MODULE.decisive_post_boundary_probe(Path("unused"), datetime.now(timezone.utc) - timedelta(seconds=101), 100)
    assert result["tokenRejected"] is False
    assert result["observedUsername"].startswith("system:serviceaccount:")


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("spec", "authorization", "retryGranted"), True),
        (("spec", "installation", "positiveServerDryRunRequired"), True),
        (("spec", "installation", "maximumSubmissions"), 2),
        (("spec", "installation", "automaticRollbackAllowed"), True),
        (("spec", "credential", "mandatoryFirstPostBoundaryProbe"), False),
        (("spec", "toolchain", "binaryDigest"), "sha256:" + "0" * 64),
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
