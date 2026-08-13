from __future__ import annotations

import copy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import controlled_m0a_execution_v6 as module  # noqa: E402


CANDIDATE = ROOT / "m0a-execution-candidate-v6.yaml"


def grant(tmp_path: Path) -> Path:
    now = datetime.now(timezone.utc)
    value = {
        "spec": {
            "version": "ok141-m0a-combined-grant/v6",
            "candidateDigest": module.sha(CANDIDATE),
            "authority": "github:arashkaffamanesh",
            "decision": "GO", "mutationAuthorized": True,
            "credentialGrant": {"gate": "M0A-C1-v6", "granted": True, "grantID": "c"},
            "admissionGrant": {"gate": "M0A-A1-v6", "granted": True, "grantID": "a"},
            "installationGrant": {"gate": "M0a-I-v6", "granted": True, "grantID": "i"},
            "validFrom": (now - timedelta(minutes=1)).isoformat(),
            "validUntil": (now + timedelta(minutes=1)).isoformat(),
            "maximumRuns": 1,
            "evidenceOutputPath": "/private/tmp/ok141-v6-test.json",
            "retryGranted": False, "rollbackGranted": False, "targetConvergenceGranted": False,
            "m0bInstallationGranted": False, "go1Granted": False,
            "evidencePublicationGranted": False, "failureInjectionGranted": False,
        }
    }
    path = tmp_path / "grant.yaml"
    path.write_text(yaml.safe_dump(value, sort_keys=False))
    return path


def test_candidate_and_digest_verify() -> None:
    document, _, _, _ = module.verify_candidate(CANDIDATE)
    assert document["spec"]["authorization"]["mutationAuthorized"] is False
    assert module.sha(CANDIDATE) == (ROOT / "m0a-execution-candidate-v6.sha256").read_text().strip()


def test_exact_grant_can_be_verified_offline(tmp_path: Path) -> None:
    assert module.verify_grant(CANDIDATE, grant(tmp_path))["maximumRuns"] == 1


def test_duplicate_grant_id_fails_closed(tmp_path: Path) -> None:
    path = grant(tmp_path)
    value = yaml.safe_load(path.read_text())
    value["spec"]["admissionGrant"]["grantID"] = "c"
    path.write_text(yaml.safe_dump(value, sort_keys=False))
    with pytest.raises(module.ExecutionError, match="distinct"):
        module.verify_grant(CANDIDATE, path)


def test_template_is_no_go() -> None:
    spec = yaml.safe_load((ROOT / "m0a-combined-grant-v6.template.yaml").read_text())["spec"]
    assert spec["candidateDigest"] == module.sha(CANDIDATE)
    assert spec["decision"] == "NO-GO"
    assert spec["mutationAuthorized"] is False
