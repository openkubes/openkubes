from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from verify_m0a_v2_risk_acceptance_record import VerificationError, verify  # noqa: E402


ACCEPTANCE = ROOT / "m0a-v2-risk-acceptance-v1.yaml"
DIGEST = ROOT / "m0a-v2-risk-acceptance-v1.sha256"


def load() -> dict:
    return yaml.safe_load(ACCEPTANCE.read_text())


def write_record(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "acceptance.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    return path


def test_canonical_record_and_digest_are_valid() -> None:
    assert verify(ACCEPTANCE) == DIGEST.read_text().strip()


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("spec", "claimBoundaries", "productionUseAllowed"), True),
        (("spec", "claimBoundaries", "retryAllowed"), True),
        (("spec", "authorization", "credentialBootstrapGranted"), True),
        (("spec", "authorization", "admissionBootstrapGranted"), True),
        (("spec", "authorization", "caaphInstallationGranted"), True),
    ],
)
def test_acceptance_cannot_infer_authority(tmp_path: Path, path: tuple[str, ...], value) -> None:
    document = copy.deepcopy(load())
    cursor = document
    for segment in path[:-1]:
        cursor = cursor[segment]
    cursor[path[-1]] = value

    with pytest.raises(VerificationError):
        verify(write_record(tmp_path, document))
