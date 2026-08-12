from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from verify_m0a_v5_security_boundary import VerificationError, verify  # noqa: E402


CANDIDATE = ROOT / "m0a-v5-security-boundary.yaml"
DIGEST = ROOT / "m0a-v5-security-boundary.sha256"


def load() -> dict:
    return yaml.safe_load(CANDIDATE.read_text())


def write(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "candidate.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    return path


def test_candidate_and_digest_verify() -> None:
    assert verify(CANDIDATE) == DIGEST.read_text().strip()


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("spec", "cause", "createFailureCause"), "PROVEN"),
        (("spec", "toolchain", "clientVersionMustEqualServerVersion"), False),
        (("spec", "submissionBoundary", "positiveServerDryRunRequired"), True),
        (("spec", "submissionBoundary", "fullStreamServerDryRunFeasible"), True),
        (("spec", "submissionBoundary", "maximumRealSubmissions"), 2),
        (("spec", "submissionBoundary", "automaticRetryAllowed"), True),
        (("spec", "submissionBoundary", "automaticRollbackAllowed"), True),
        (("spec", "diagnosticBoundary", "stderrMaximumBytes"), 100000),
        (("spec", "credentialBoundary", "mandatoryFirstPostBoundaryProbe"), False),
        (("spec", "authorization", "mutationAuthorized"), True),
    ],
)
def test_boundary_tampering_fails_closed(tmp_path: Path, path: tuple[str, ...], value) -> None:
    document = copy.deepcopy(load())
    cursor = document
    for segment in path[:-1]:
        cursor = cursor[segment]
    cursor[path[-1]] = value
    with pytest.raises(VerificationError):
        verify(write(tmp_path, document))
