from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from verify_m0a_v4_first_run import VerificationError, verify  # noqa: E402


EVIDENCE = ROOT / "m0a-v4-first-run-evidence-v1.yaml"
DIGEST = ROOT / "m0a-v4-first-run-evidence-v1.sha256"


def load() -> dict:
    return yaml.safe_load(EVIDENCE.read_text())


def write(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "evidence.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    return path


def test_redacted_evidence_and_digest_verify() -> None:
    assert verify(EVIDENCE) == DIGEST.read_text().strip()


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("spec", "state"), "SUCCESS"),
        (("spec", "execution", "runsConsumed"), 0),
        (("spec", "execution", "retryAuthorized"), True),
        (("spec", "installation", "postSubmissionInventory", "present"), 1),
        (("spec", "installation", "causeClassification"), "PROVEN"),
        (("spec", "conclusion", "tokenRejectionProven"), True),
        (("spec", "conclusion", "retryAllowed"), True),
        (("spec", "authorization", "evidencePublicationGranted"), True),
        (("spec", "redaction", "tokensIncluded"), True),
    ],
)
def test_claim_or_authority_inference_fails_closed(tmp_path: Path, path: tuple[str, ...], value) -> None:
    document = copy.deepcopy(load())
    cursor = document
    for segment in path[:-1]:
        cursor = cursor[segment]
    cursor[path[-1]] = value
    with pytest.raises(VerificationError):
        verify(write(tmp_path, document))


def test_candidate_binding_tamper_fails_closed(tmp_path: Path) -> None:
    document = load()
    document["spec"]["references"]["candidate"]["digest"] = "sha256:" + "0" * 64
    with pytest.raises(VerificationError):
        verify(write(tmp_path, document))
