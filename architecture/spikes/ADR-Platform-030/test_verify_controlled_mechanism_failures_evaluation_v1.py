import importlib.util
from pathlib import Path

import pytest
import yaml


HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "verify_controlled_mechanism_failures_evaluation_v1.py"
SPEC = importlib.util.spec_from_file_location("verify_controlled_failures", SCRIPT)
VERIFY = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VERIFY)


def test_evaluation_verifies():
    assert VERIFY.verify().startswith("sha256:")


def test_publication_candidate_binds_exact_evaluation():
    candidate = yaml.safe_load(
        (
            HERE
            / "controlled-mechanism-failures-evaluation-publication-candidate-v1.yaml"
        ).read_text()
    )
    assert candidate["spec"]["state"] == "READY-NO-GO"
    assert candidate["spec"]["evaluation"]["digest"] == VERIFY.verify()
    assert candidate["spec"]["authorization"]["decision"] == "NO-GO"
    assert not any(
        value
        for key, value in candidate["spec"]["authorization"].items()
        if key.endswith("Granted")
    )


def test_final_classification_cannot_be_claimed(tmp_path: Path):
    text = VERIFY.EVALUATION.read_text().replace(
        "Overall OK-141 A/B/C/D:       unclassified",
        "Overall OK-141 A/B/C/D:       A",
    )
    path = tmp_path / "tampered.md"
    path.write_text(text)
    with pytest.raises(VERIFY.VerificationError):
        VERIFY.verify(path)


def test_delete_cannot_be_claimed_granted(tmp_path: Path):
    text = VERIFY.EVALUATION.read_text().replace(
        "Delete:                       NOT GRANTED",
        "Delete:                       GRANTED",
    )
    path = tmp_path / "tampered.md"
    path.write_text(text)
    with pytest.raises(VERIFY.VerificationError):
        VERIFY.verify(path)


def test_credential_like_payload_fails_closed(tmp_path: Path):
    path = tmp_path / "tampered.md"
    path.write_text(VERIFY.EVALUATION.read_text() + "\nbearerToken: unsafe\n")
    with pytest.raises(VERIFY.VerificationError):
        VERIFY.verify(path)
