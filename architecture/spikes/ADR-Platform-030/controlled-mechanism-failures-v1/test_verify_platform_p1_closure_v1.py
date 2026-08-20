import importlib.util
from pathlib import Path

import pytest
import yaml


HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "verify_platform_p1_closure_v1.py"
SPEC = importlib.util.spec_from_file_location("verify_platform_p1", SCRIPT)
VERIFY = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VERIFY)


def test_public_evidence_verifies():
    assert VERIFY.verify().startswith("sha256:")


def test_publication_candidate_binds_exact_redacted_evidence():
    candidate = yaml.safe_load(
        (HERE / "platform-p1-closure-publication-candidate-v1.yaml").read_text()
    )
    assert candidate["spec"]["state"] == "READY-NO-GO"
    assert candidate["spec"]["closureEvidence"]["digest"] == VERIFY.verify()
    assert candidate["spec"]["authorization"]["decision"] == "NO-GO"
    assert not any(
        value
        for key, value in candidate["spec"]["authorization"].items()
        if key.endswith("Granted")
    )


def test_platform_ready_during_fault_must_be_false(tmp_path: Path):
    value = yaml.safe_load(VERIFY.EVIDENCE.read_text())
    value["spec"]["result"]["PlatformReadyDuringFault"] = True
    path = tmp_path / "tampered.yaml"
    path.write_text(yaml.safe_dump(value))
    with pytest.raises(VERIFY.VerificationError):
        VERIFY.verify(path)


def test_runner_repair_claim_must_be_false(tmp_path: Path):
    value = yaml.safe_load(VERIFY.EVIDENCE.read_text())
    value["spec"]["safety"]["runnerRepairPerformed"] = True
    path = tmp_path / "tampered.yaml"
    path.write_text(yaml.safe_dump(value))
    with pytest.raises(VERIFY.VerificationError):
        VERIFY.verify(path)


def test_forbidden_payload_category_fails_closed(tmp_path: Path):
    value = yaml.safe_load(VERIFY.EVIDENCE.read_text())
    value["spec"]["unsafeKubeconfig"] = "payload"
    path = tmp_path / "tampered.yaml"
    path.write_text(yaml.safe_dump(value))
    with pytest.raises(VERIFY.VerificationError):
        VERIFY.verify(path)
