import copy
import datetime as dt
import importlib.util
import json
from pathlib import Path

import pytest
import yaml


HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "bounded_platform_failure_p1_v1.py"
SPEC = importlib.util.spec_from_file_location("bounded_p1", SCRIPT)
P1 = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(P1)


def application_spec(path: str = "dashboards") -> dict:
    return {
        "destination": {"namespace": "ok-observability", "server": "redacted"},
        "project": "ok141-platform",
        "source": {
            "path": path,
            "repoURL": "redacted",
            "targetRevision": "c09c18759aeb7526d22106ccb001599f5f06bc4e",
        },
        "syncPolicy": {"automated": {"prune": True, "selfHeal": True}},
    }


def application_object() -> dict:
    return {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Application",
        "metadata": {
            "name": "disposable-ok141-observability-dashboards",
            "namespace": "argocd",
            "uid": "uid",
            "resourceVersion": "10",
            "managedFields": [{"manager": "test"}],
        },
        "spec": application_spec(),
        "status": {"health": {"status": "Healthy"}},
    }


def test_candidate_verifies_and_is_non_authorizing():
    candidate = P1.validate_candidate()
    assert candidate["spec"]["authorization"]["decision"] == "NO-GO"
    assert not any(
        value
        for key, value in candidate["spec"]["authorization"].items()
        if key.endswith("Granted")
    )


def test_fault_changes_only_the_exact_path():
    baseline = application_spec()
    changed = P1.fault_spec(
        baseline,
        "dashboards",
        "dashboards/ok141-controlled-failure-missing",
    )
    assert changed["source"]["path"] == "dashboards/ok141-controlled-failure-missing"
    restored = copy.deepcopy(changed)
    restored["source"]["path"] = baseline["source"]["path"]
    assert restored == baseline


def test_fault_rejects_wrong_baseline():
    with pytest.raises(P1.P1Error):
        P1.fault_spec(application_spec("other"), "dashboards", "missing")


def test_replace_document_preserves_concurrency_and_removes_status():
    current = application_object()
    payload = json.loads(
        P1.safe_replace_document(
            current,
            P1.fault_spec(current["spec"], "dashboards", "missing"),
        )
    )
    assert payload["metadata"]["uid"] == "uid"
    assert payload["metadata"]["resourceVersion"] == "10"
    assert "managedFields" not in payload["metadata"]
    assert "status" not in payload
    assert payload["spec"]["source"]["path"] == "missing"


def test_condition_freshness_is_fail_closed():
    condition = {
        "type": "ComparisonError",
        "lastTransitionTime": "2026-08-20T12:00:01Z",
    }
    assert P1.condition_after(condition, "2026-08-20T12:00:00Z")
    assert not P1.condition_after(condition, "2026-08-20T12:00:02Z")
    assert not P1.condition_after({"type": "ComparisonError"}, "2026-08-20T12:00:00Z")


def test_grant_template_cannot_authorize_execution():
    grant = yaml.safe_load((HERE / "platform-p1-grant-v1.template.yaml").read_text())
    assert grant["spec"]["decision"] == "NOT-GRANTED"
    assert not any(
        value
        for key, value in grant["spec"].items()
        if key.endswith("Granted")
    )


def test_publication_candidate_binds_exact_artifacts():
    candidate = yaml.safe_load(
        (HERE / "platform-p1-publication-candidate-v1.yaml").read_text()
    )
    artifacts = candidate["spec"]["artifacts"]
    for binding in artifacts.values():
        assert binding["digest"] == P1.digest(HERE / binding["path"])
    assert candidate["spec"]["authorization"]["decision"] == "NO-GO"
    assert not any(
        value
        for key, value in candidate["spec"]["authorization"].items()
        if key.endswith("Granted")
    )


def test_overlong_grant_is_rejected(tmp_path: Path):
    grant = yaml.safe_load((HERE / "platform-p1-grant-v1.template.yaml").read_text())
    grant["spec"].update(
        {
            "decision": "GO",
            "candidateDigest": P1.digest(P1.CANDIDATE),
            "grantID": "test",
            "issuedAt": "2026-08-20T12:00:00Z",
            "expiresAt": "2026-08-20T12:46:00Z",
            "sharedCredentialUseGranted": True,
            "workloadCredentialUseGranted": True,
            "failureInjectionGranted": True,
            "boundedObservationGranted": True,
            "exactRestoreGranted": True,
        }
    )
    path = tmp_path / "grant.yaml"
    path.write_text(yaml.safe_dump(grant))
    with pytest.raises(P1.P1Error):
        P1.validate_grant(
            P1.CANDIDATE,
            path,
            current=dt.datetime(2026, 8, 20, 12, 1, tzinfo=dt.timezone.utc),
        )
