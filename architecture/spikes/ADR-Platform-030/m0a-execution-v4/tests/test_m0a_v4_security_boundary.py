from pathlib import Path

import pytest
import yaml


HERE = Path(__file__).resolve().parents[1]


def load_verifier(filename: str, module_name: str):
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(module_name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


SECURITY = load_verifier("verify_m0a_v4_security_boundary.py", "ok141_m0a_v4_security")
RISK = load_verifier("verify_m0a_v4_risk_candidate.py", "ok141_m0a_v4_risk")
UPSTREAM = load_verifier("verify_m0a_v4_upstream_semantics.py", "ok141_m0a_v4_upstream")


def write_variant(tmp_path: Path, source: Path, mutate) -> Path:
    data = yaml.safe_load(source.read_text())
    mutate(data)
    target = tmp_path / source.name
    target.write_text(yaml.safe_dump(data, sort_keys=False))
    return target


def test_security_candidate_and_digest_pass():
    assert SECURITY.verify(HERE / "m0a-v4-security-boundary.yaml").startswith("sha256:")


def test_upstream_semantics_and_digest_pass():
    assert UPSTREAM.verify(HERE / "m0a-v4-upstream-semantics.yaml").startswith("sha256:")


def test_risk_candidate_and_digest_pass():
    assert RISK.verify(HERE / "m0a-v4-risk-acceptance-candidate.yaml").startswith("sha256:")


def test_server_side_apply_fails_closed(tmp_path):
    candidate = write_variant(
        tmp_path,
        HERE / "m0a-v4-security-boundary.yaml",
        lambda data: data["spec"]["submissionBoundary"].update(serverSideApply=True),
    )
    with pytest.raises(SECURITY.VerificationError):
        SECURITY.verify(candidate)


def test_patch_permission_fails_closed(tmp_path):
    candidate = write_variant(
        tmp_path,
        HERE / "m0a-v4-security-boundary.yaml",
        lambda data: data["spec"]["retainedSecurityControls"].update(patchAllowed=True),
    )
    with pytest.raises(SECURITY.VerificationError):
        SECURITY.verify(candidate)


def test_early_expiry_deadline_fails_closed(tmp_path):
    candidate = write_variant(
        tmp_path,
        HERE / "m0a-v4-security-boundary.yaml",
        lambda data: data["spec"]["revocationBoundary"].update(observationDeadline="token-expirationTimestamp-plus-30s"),
    )
    with pytest.raises(SECURITY.VerificationError):
        SECURITY.verify(candidate)


def test_upstream_cache_tamper_fails_closed(tmp_path):
    candidate = write_variant(
        tmp_path,
        HERE / "m0a-v4-upstream-semantics.yaml",
        lambda data: data["spec"]["tokenExpiry"]["authenticationOptions"].update(defaultSuccessCacheSeconds=0),
    )
    with pytest.raises(UPSTREAM.VerificationError):
        UPSTREAM.verify(candidate)


def test_automatic_rollback_fails_closed(tmp_path):
    candidate = write_variant(
        tmp_path,
        HERE / "m0a-v4-security-boundary.yaml",
        lambda data: data["spec"]["submissionBoundary"].update(automaticRollbackAllowed=True),
    )
    with pytest.raises(SECURITY.VerificationError):
        SECURITY.verify(candidate)


def test_risk_acceptance_fails_closed(tmp_path):
    candidate = write_variant(
        tmp_path,
        HERE / "m0a-v4-risk-acceptance-candidate.yaml",
        lambda data: data["spec"]["acceptance"].update(accepted=True),
    )
    with pytest.raises(RISK.VerificationError):
        RISK.verify(candidate)


def test_risk_authority_fails_closed(tmp_path):
    candidate = write_variant(
        tmp_path,
        HERE / "m0a-v4-risk-acceptance-candidate.yaml",
        lambda data: data["spec"]["authorization"].update(retryGranted=True),
    )
    with pytest.raises(RISK.VerificationError):
        RISK.verify(candidate)
