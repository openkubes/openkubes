from __future__ import annotations

import copy
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("controlled_m0a_execution_v3_grant", ROOT / "controlled_m0a_execution_v3.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)

CANDIDATE = ROOT / "m0a-execution-candidate-v3.yaml"
GRANT = ROOT / "m0a-combined-grant-v3.yaml"
GRANT_DIGEST = ROOT / "m0a-combined-grant-v3.sha256"


def load() -> dict:
    return yaml.safe_load(GRANT.read_text())


def write_grant(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "grant.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    return path


def test_exact_grant_and_digest_verify_in_window() -> None:
    assert MODULE.sha(GRANT) == GRANT_DIGEST.read_text().strip()
    result = MODULE.verify_grant(CANDIDATE, GRANT, datetime(2026, 8, 12, 17, 0, tzinfo=timezone.utc))
    assert result["maximumRuns"] == 1
    assert result["candidateDigest"] == MODULE.sha(CANDIDATE)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("spec", "decision"), "NO-GO"),
        (("spec", "mutationAuthorized"), False),
        (("spec", "maximumRuns"), 2),
        (("spec", "rollbackGranted"), True),
        (("spec", "targetConvergenceGranted"), True),
        (("spec", "go1Granted"), True),
        (("spec", "evidencePublicationGranted"), True),
    ],
)
def test_grant_tampering_fails_closed(tmp_path: Path, path: tuple[str, ...], value) -> None:
    document = copy.deepcopy(load())
    cursor = document
    for segment in path[:-1]:
        cursor = cursor[segment]
    cursor[path[-1]] = value
    with pytest.raises(MODULE.ExecutionError):
        MODULE.verify_grant(CANDIDATE, write_grant(tmp_path, document), datetime(2026, 8, 12, 17, 0, tzinfo=timezone.utc))


def test_grant_is_not_valid_before_or_after_window() -> None:
    with pytest.raises(MODULE.ExecutionError, match="outside"):
        MODULE.verify_grant(CANDIDATE, GRANT, datetime(2026, 8, 12, 16, 44, tzinfo=timezone.utc))
    with pytest.raises(MODULE.ExecutionError, match="outside"):
        MODULE.verify_grant(CANDIDATE, GRANT, datetime(2026, 8, 12, 19, 46, tzinfo=timezone.utc))


def test_three_grant_ids_are_exact_and_distinct() -> None:
    spec = load()["spec"]
    assert [spec[key]["grantID"] for key in ("credentialGrant", "admissionGrant", "installationGrant")] == [
        "ok141-m0a-c1-v3-20260812-01",
        "ok141-m0a-a1-v3-20260812-01",
        "ok141-m0a-i-v3-20260812-01",
    ]
