from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from verify_m0a_v4_risk_acceptance import VerificationError, verify  # noqa: E402


EVIDENCE = ROOT / "m0a-v4-risk-acceptance-v1.yaml"
DIGEST = ROOT / "m0a-v4-risk-acceptance-v1.sha256"


def load() -> dict:
    return yaml.safe_load(EVIDENCE.read_text())


def write_evidence(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "acceptance.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    return path


def test_canonical_acceptance_and_digest_are_valid() -> None:
    assert verify(EVIDENCE) == DIGEST.read_text().strip()


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("spec", "state"), "EXECUTION-AUTHORIZED"),
        (("spec", "claimBoundaries", "submissionAtomic"), True),
        (("spec", "claimBoundaries", "automaticRetryAllowed"), True),
        (("spec", "claimBoundaries", "automaticRollbackAllowed"), True),
        (("spec", "claimBoundaries", "immediateTokenRevocationProven"), True),
        (("spec", "authorization", "mutationAuthorized"), True),
        (("spec", "authorization", "credentialBootstrapGranted"), True),
        (("spec", "authorization", "evidencePublicationGranted"), True),
    ],
)
def test_authority_or_claim_inference_fails_closed(tmp_path: Path, path: tuple[str, ...], value) -> None:
    document = copy.deepcopy(load())
    cursor = document
    for segment in path[:-1]:
        cursor = cursor[segment]
    cursor[path[-1]] = value
    with pytest.raises(VerificationError):
        verify(write_evidence(tmp_path, document))


def test_security_binding_tampering_fails_closed(tmp_path: Path) -> None:
    document = load()
    document["spec"]["references"]["securityBoundary"]["digest"] = "sha256:" + "0" * 64
    with pytest.raises(VerificationError):
        verify(write_evidence(tmp_path, document))
