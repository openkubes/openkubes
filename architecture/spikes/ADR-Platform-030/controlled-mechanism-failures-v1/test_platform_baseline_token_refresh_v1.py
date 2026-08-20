import datetime as dt
import importlib.util
from pathlib import Path

import pytest
import yaml


HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "bounded_platform_baseline_token_refresh_v1.py"
SPEC = importlib.util.spec_from_file_location("refresh", SCRIPT)
REFRESH = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(REFRESH)


def registration_secret() -> dict:
    config = {
        "bearerToken": "old",
        "tlsClientConfig": {"caData": "Y2E="},
    }
    encode = lambda value: __import__("base64").b64encode(value).decode()
    return {
        "metadata": {"uid": "uid", "resourceVersion": "1"},
        "data": {
            "clusterResources": encode(b"true"),
            "config": encode(__import__("json").dumps(config).encode()),
            "name": encode(b"target"),
            "namespaces": encode(b"ns"),
            "project": encode(b"project"),
            "server": encode(b"https://target"),
        },
    }


def test_replacement_changes_only_config_token_and_annotation():
    current = registration_secret()
    payload, unchanged = REFRESH.replacement_secret(current, "new", "expiry")
    value = __import__("json").loads(payload)
    assert len(unchanged) == 5
    assert value["metadata"]["uid"] == "uid"
    assert value["metadata"]["resourceVersion"] == "1"
    assert value["metadata"]["annotations"]["openkubes.io/token-expiration"] == "expiry"


def test_registration_shape_drift_fails_closed():
    current = registration_secret()
    del current["data"]["project"]
    with pytest.raises(REFRESH.RefreshError):
        REFRESH.registration_identity(current)


def test_application_ready_allows_only_orphan_warning():
    value = {
        "status": {
            "sync": {"status": "Synced", "revision": "rev"},
            "health": {"status": "Healthy"},
            "conditions": [{"type": "OrphanedResourceWarning"}],
        }
    }
    assert REFRESH.application_ready(value, "rev")
    value["status"]["conditions"].append({"type": "ComparisonError"})
    assert not REFRESH.application_ready(value, "rev")


def test_grant_template_is_non_authorizing():
    value = yaml.safe_load((HERE / "platform-baseline-token-refresh-grant-v1.template.yaml").read_text())
    assert value["spec"]["decision"] == "NOT-GRANTED"
    assert not any(item for key, item in value["spec"].items() if key.endswith("Granted"))


def test_overlong_grant_is_rejected(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(REFRESH, "validate_candidate", lambda _: {})
    monkeypatch.setattr(REFRESH, "digest", lambda _: "sha256:candidate")
    spec = {
        "decision": "GO",
        "candidateDigest": "sha256:candidate",
        "authority": "github:arashkaffamanesh",
        "singleRun": True,
        "consumed": False,
        "issuedAt": "2026-08-20T10:00:00Z",
        "expiresAt": "2026-08-20T11:00:00Z",
    }
    for key in (
        "registrationSecretReadGranted",
        "workloadAdminCredentialUseGranted",
        "tokenRequestGranted",
        "targetProbeGranted",
        "registrationSecretReplaceGranted",
        "applicationObservationGranted",
    ):
        spec[key] = True
    for key in (
        "retryGranted",
        "rollbackGranted",
        "cleanupGranted",
        "failureInjectionGranted",
        "evidencePublicationGranted",
    ):
        spec[key] = False
    path = tmp_path / "grant.yaml"
    path.write_text(yaml.safe_dump({"kind": "PlatformBaselineTokenRefreshGrant", "spec": spec}))
    with pytest.raises(REFRESH.RefreshError):
        REFRESH.validate_grant(
            HERE / "candidate.yaml",
            path,
            current=dt.datetime(2026, 8, 20, 10, 30, tzinfo=dt.timezone.utc),
        )
