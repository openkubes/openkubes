from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from verify_m0a_v5_expired_grant import VerificationError, verify  # noqa: E402


RECORD = ROOT / "m0a-expired-grant-v5-20260812.yaml"
DIGEST = ROOT / "m0a-expired-grant-v5-20260812.sha256"


def load() -> dict:
    return yaml.safe_load(RECORD.read_text())


def write(tmp_path: Path, value: dict) -> Path:
    path = tmp_path / "record.yaml"
    path.write_text(yaml.safe_dump(value, sort_keys=False))
    return path


def test_record_and_digest_verify() -> None:
    assert verify(RECORD) == DIGEST.read_text().strip()


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("spec", "state"), "GRANTED"),
        (("spec", "effectiveDecision"), "GO"),
        (("spec", "mutationAuthorized"), True),
        (("spec", "expired"), False),
        (("spec", "reusable"), True),
        (("spec", "actualRuns"), 1),
        (("spec", "evidenceCreated"), True),
        (("spec", "retryGranted"), True),
    ],
)
def test_authority_inference_fails_closed(tmp_path: Path, path: tuple[str, ...], value) -> None:
    document = copy.deepcopy(load())
    cursor = document
    for segment in path[:-1]:
        cursor = cursor[segment]
    cursor[path[-1]] = value
    with pytest.raises((VerificationError, KeyError)):
        verify(write(tmp_path, document))
