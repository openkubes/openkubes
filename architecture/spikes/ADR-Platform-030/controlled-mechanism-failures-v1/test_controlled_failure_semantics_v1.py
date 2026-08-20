from copy import deepcopy

from controlled_failure_semantics_v1 import network_ready, platform_ready


REVISION = "c09c18759aeb7526d22106ccb001599f5f06bc4e"


def current_condition(condition_type: str) -> dict:
    return {
        "type": condition_type,
        "status": "True",
        "observedGeneration": 1,
    }


def hcp() -> dict:
    return {
        "metadata": {"generation": 1},
        "spec": {"version": "1.19.6"},
        "status": {
            "conditions": [
                current_condition("Ready"),
                current_condition("HelmReleaseProxySpecsUpToDate"),
                current_condition("HelmReleaseProxiesReady"),
            ]
        },
    }


def hrp() -> dict:
    return {
        "metadata": {"generation": 1},
        "spec": {"version": "1.19.6"},
        "status": {
            "conditions": [
                current_condition("Ready"),
                current_condition("HelmReleaseReady"),
            ]
        },
    }


def applications() -> list[dict]:
    return [
        {
            "metadata": {"name": name, "generation": 1},
            "status": {
                "observedGeneration": 1,
                "conditions": [],
                "sync": {"status": "Synced", "revision": REVISION},
                "health": {"status": "Healthy"},
            },
        }
        for name in (
            "disposable-ok141-observability-core",
            "disposable-ok141-observability-alerting",
            "disposable-ok141-observability-dashboards",
        )
    ]


def test_network_ready_requires_desired_and_runtime_truth():
    assert network_ready(hcp(), [hrp()], runtime_ready=True)


def test_wrong_hcp_version_fails_closed_while_runtime_stays_healthy():
    changed = hcp()
    changed["spec"]["version"] = "0.0.0-ok141-controlled-failure"
    assert not network_ready(changed, [hrp()], runtime_ready=True)


def test_stale_hcp_or_failed_runtime_fails_closed():
    stale = hcp()
    stale["metadata"]["generation"] = 2
    assert not network_ready(stale, [hrp()], runtime_ready=True)
    assert not network_ready(hcp(), [hrp()], runtime_ready=False)


def test_platform_ready_requires_exact_current_set():
    assert platform_ready(applications(), expected_revision=REVISION)


def test_manifest_generation_condition_fails_closed():
    failed = applications()
    failed[2]["metadata"]["generation"] = 2
    failed[2]["status"]["observedGeneration"] = 2
    failed[2]["status"]["conditions"] = [{"type": "ComparisonError"}]
    failed[2]["status"]["sync"]["status"] = "Unknown"
    assert not platform_ready(failed, expected_revision=REVISION)


def test_stale_wrong_revision_or_missing_application_fails_closed():
    stale = applications()
    stale[0]["metadata"]["generation"] = 2
    assert not platform_ready(stale, expected_revision=REVISION)
    wrong = applications()
    wrong[1]["status"]["sync"]["revision"] = "wrong"
    assert not platform_ready(wrong, expected_revision=REVISION)
    assert not platform_ready(applications()[:-1], expected_revision=REVISION)
