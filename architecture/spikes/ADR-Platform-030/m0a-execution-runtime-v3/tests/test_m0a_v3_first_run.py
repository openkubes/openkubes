from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from verify_m0a_v3_first_run import VerificationError, verify  # noqa: E402


EVIDENCE = ROOT / "m0a-v3-first-run-evidence-v1.yaml"
DIGEST = ROOT / "m0a-v3-first-run-evidence-v1.sha256"


def load() -> dict:
    return yaml.safe_load(EVIDENCE.read_text())


def write_evidence(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "evidence.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    return path


def test_canonical_evidence_and_digest_are_valid() -> None:
    assert verify(EVIDENCE) == DIGEST.read_text().strip()


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("spec", "state"), "SUCCESS"),
        (("spec", "execution", "retryAuthorized"), True),
        (("spec", "execution", "rawLocalEvidencePublishable"), True),
        (("spec", "credential", "expiryBoundRejectionProbe", "result"), "PASS"),
        (("spec", "installation", "result"), "SUCCESS"),
        (("spec", "installation", "likelyCause", "classification"), "PROVEN"),
        (("spec", "authorization", "evidencePublicationGranted"), True),
        (("spec", "authorization", "retryGranted"), True),
    ],
)
def test_forbidden_claims_fail_closed(tmp_path: Path, path: tuple[str, ...], value) -> None:
    document = copy.deepcopy(load())
    cursor = document
    for segment in path[:-1]:
        cursor = cursor[segment]
    cursor[path[-1]] = value
    with pytest.raises(VerificationError):
        verify(write_evidence(tmp_path, document))


def test_retained_partial_installation_fails_closed(tmp_path: Path) -> None:
    document = load()
    document["spec"]["postFailureObservation"]["caaphInstallationObjectsPresent"] = 1
    with pytest.raises(VerificationError):
        verify(write_evidence(tmp_path, document))
