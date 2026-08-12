from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from authorization_probe_v3 import can_i_args, token_request_denial_args  # noqa: E402
from verify_m0a_v3_security_boundary import VerificationError, verify  # noqa: E402


CANDIDATE = ROOT / "m0a-v3-security-boundary.yaml"
DIGEST = ROOT / "m0a-v3-security-boundary.sha256"


def load() -> dict:
    return yaml.safe_load(CANDIDATE.read_text())


def write_candidate(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "candidate.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    return path


def test_canonical_candidate_and_digest_are_valid() -> None:
    assert verify(CANDIDATE) == DIGEST.read_text().strip()


def test_token_request_probe_uses_explicit_subresource() -> None:
    assert token_request_denial_args() == [
        "auth", "can-i", "create", "serviceaccounts",
        "--subresource", "token", "--namespace", "openkubes-system",
    ]


def test_name_and_subresource_cannot_be_conflated() -> None:
    with pytest.raises(ValueError, match="must not be combined"):
        can_i_args("create", "serviceaccounts", name="token", subresource="token")


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("spec", "state"), "READY"),
        (("spec", "cause", "grantConsumed"), False),
        (("spec", "tokenRequestAuthorizationProof", "installerMayIssueToken"), True),
        (("spec", "tokenRequestAuthorizationProof", "requiredForm"), ["auth", "can-i", "create", "serviceaccounts/token"]),
        (("spec", "revocationBoundary", "immediateRejectionClaim"), True),
        (("spec", "revocationBoundary", "clockSkewToleranceSeconds"), 300),
        (("spec", "authorization", "retryGranted"), True),
        (("spec", "authorization", "evidencePublicationGranted"), True),
    ],
)
def test_unsafe_or_unproven_changes_fail_closed(tmp_path: Path, path: tuple[str, ...], value) -> None:
    document = copy.deepcopy(load())
    cursor = document
    for segment in path[:-1]:
        cursor = cursor[segment]
    cursor[path[-1]] = value
    with pytest.raises(VerificationError):
        verify(write_candidate(tmp_path, document))
