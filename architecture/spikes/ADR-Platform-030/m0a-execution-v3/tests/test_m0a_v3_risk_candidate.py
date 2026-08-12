from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from verify_m0a_v3_risk_candidate import VerificationError, verify  # noqa: E402


CANDIDATE = ROOT / "m0a-v3-risk-acceptance-candidate.yaml"
DIGEST = ROOT / "m0a-v3-risk-acceptance-candidate.sha256"


def load() -> dict:
    return yaml.safe_load(CANDIDATE.read_text())


def write_candidate(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "risk.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    return path


def test_canonical_risk_candidate_and_digest_are_valid() -> None:
    assert verify(CANDIDATE) == DIGEST.read_text().strip()


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("spec", "state"), "ACCEPTED"),
        (("spec", "acceptance", "accepted"), True),
        (("spec", "authorization", "mutationAuthorized"), True),
        (("spec", "authorization", "retryGranted"), True),
    ],
)
def test_acceptance_or_authority_inference_fails_closed(tmp_path: Path, path: tuple[str, ...], value) -> None:
    document = copy.deepcopy(load())
    cursor = document
    for segment in path[:-1]:
        cursor = cursor[segment]
    cursor[path[-1]] = value
    with pytest.raises(VerificationError):
        verify(write_candidate(tmp_path, document))


def test_security_digest_tampering_fails_closed(tmp_path: Path) -> None:
    document = load()
    document["spec"]["references"]["securityBoundary"]["digest"] = "sha256:" + "0" * 64
    with pytest.raises(VerificationError):
        verify(write_candidate(tmp_path, document))
