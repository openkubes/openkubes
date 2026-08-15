from __future__ import annotations

import copy
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("controlled_m0a_execution_v2_grant", ROOT / "controlled_m0a_execution_v2.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)

CANDIDATE = ROOT / "m0a-execution-candidate-v2.yaml"
GRANT = ROOT / "m0a-combined-grant-v2.yaml"


def write(tmp_path: Path, value: dict) -> Path:
    path = tmp_path / "grant.yaml"
    path.write_text(yaml.safe_dump(value, sort_keys=False))
    return path


def test_exact_grant_verifies_inside_bound_window() -> None:
    result = MODULE.verify_grant(CANDIDATE, GRANT, datetime(2026, 8, 12, 12, 40, tzinfo=timezone.utc))
    assert result["maximumRuns"] == 1
    assert result["rollbackGranted"] is False


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("spec", "candidateDigest"), "sha256:" + "0" * 64),
        (("spec", "credentialGrant", "grantID"), "ok141-m0a-a1-v2-20260812-01"),
        (("spec", "maximumRuns"), 2),
        (("spec", "rollbackGranted"), True),
        (("spec", "evidencePublicationGranted"), True),
        (("spec", "go1Granted"), True),
    ],
)
def test_grant_tampering_fails_closed(tmp_path: Path, path: tuple[str, ...], value) -> None:
    document = copy.deepcopy(yaml.safe_load(GRANT.read_text()))
    cursor = document
    for segment in path[:-1]:
        cursor = cursor[segment]
    cursor[path[-1]] = value
    with pytest.raises(MODULE.ExecutionError):
        MODULE.verify_grant(CANDIDATE, write(tmp_path, document), datetime(2026, 8, 12, 13, 0, tzinfo=timezone.utc))


def test_grant_rejected_outside_window() -> None:
    with pytest.raises(MODULE.ExecutionError, match="outside"):
        MODULE.verify_grant(CANDIDATE, GRANT, datetime(2026, 8, 12, 15, 40, 1, tzinfo=timezone.utc))
