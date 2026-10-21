from datetime import datetime, timezone

import pytest

from agent_claim_adapter import ClaimRejected, plan_kagent_agent


DIGEST = "sha256:" + "a" * 64
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


def claim(**overrides):
    value = {
        "apiVersion": "agents.openkubes.io/v1alpha1",
        "kind": "AgentDeploymentClaim",
        "metadata": {"name": "docs-search", "namespace": "openkubes-agents"},
        "spec": {
            "agentRef": {"name": "agent-ok-ai-document-search", "version": "Beta 1.1", "digest": DIGEST},
            "clusterRef": "ok-shared",
            "tools": ["documents.search"],
            "authority": "read-only",
            "expiresAt": "2026-10-21T12:10:00Z",
        },
    }
    value["spec"].update(overrides)
    return value


def test_plans_kagent_manifest_without_writes():
    manifest = plan_kagent_agent(claim(), now=NOW)
    assert manifest["kind"] == "Agent"
    assert manifest["metadata"]["labels"]["agents.openkubes.io/digest"] == DIGEST
    assert manifest["spec"]["type"] == "Declarative"


@pytest.mark.parametrize("field", ["clusterRef", "authority", "expiresAt"])
def test_rejects_missing_claim_fields(field):
    data = claim()
    data["spec"].pop(field)
    with pytest.raises(ClaimRejected):
        plan_kagent_agent(data, now=NOW)


def test_rejects_expired_claim():
    with pytest.raises(ClaimRejected, match="future"):
        plan_kagent_agent(claim(expiresAt="2026-10-21T11:59:00Z"), now=NOW)
