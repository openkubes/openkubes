"""Fail-closed translation of an AgentDeploymentClaim into a kagent plan.

This module deliberately performs no Kubernetes writes. A controller can use
the returned manifest only after its own claim authorization and policy checks.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable


DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")


class ClaimRejected(ValueError):
    pass


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ClaimRejected(f"{field} is required")
    return value.strip()


def plan_kagent_agent(claim: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    if claim.get("apiVersion") != "agents.openkubes.io/v1alpha1" or claim.get("kind") != "AgentDeploymentClaim":
        raise ClaimRejected("claim apiVersion/kind is not supported")
    metadata = claim.get("metadata")
    spec = claim.get("spec")
    if not isinstance(metadata, dict) or not isinstance(spec, dict):
        raise ClaimRejected("claim metadata and spec are required")
    name = _required_string(metadata.get("name"), "metadata.name")
    namespace = _required_string(metadata.get("namespace"), "metadata.namespace")
    agent_ref = spec.get("agentRef")
    if not isinstance(agent_ref, dict):
        raise ClaimRejected("spec.agentRef is required")
    agent_name = _required_string(agent_ref.get("name"), "spec.agentRef.name")
    version = _required_string(agent_ref.get("version"), "spec.agentRef.version")
    digest = _required_string(agent_ref.get("digest"), "spec.agentRef.digest")
    if not DIGEST.fullmatch(digest):
        raise ClaimRejected("spec.agentRef.digest must be immutable sha256")
    cluster = _required_string(spec.get("clusterRef"), "spec.clusterRef")
    tools = spec.get("tools")
    if not isinstance(tools, list) or not tools or any(not isinstance(tool, str) or not tool.strip() for tool in tools):
        raise ClaimRejected("spec.tools must contain non-empty strings")
    authority = _required_string(spec.get("authority"), "spec.authority")
    expires_at = _required_string(spec.get("expiresAt"), "spec.expiresAt")
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ClaimRejected("spec.expiresAt must be ISO-8601") from error
    reference = now or datetime.now(timezone.utc)
    if expiry <= reference.astimezone(timezone.utc):
        raise ClaimRejected("spec.expiresAt must be in the future")
    return {
        "apiVersion": "kagent.dev/v1alpha2",
        "kind": "Agent",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "agents.openkubes.io/cluster": cluster,
                "agents.openkubes.io/version": version,
                "agents.openkubes.io/digest": digest,
            },
            "annotations": {
                "agents.openkubes.io/claim-authority": authority,
                "agents.openkubes.io/claim-expires-at": expires_at,
            },
        },
        "spec": {
            "type": "Declarative",
            "declarative": {
                "description": f"OpenKubes agent {agent_name} ({version})",
                "systemMessage": f"Operate only with the approved tools: {', '.join(tools)}.",
            },
        },
    }


def reconcile_kagent_claim(
    claim: dict[str, Any],
    apply_manifest: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Apply one validated plan through an injected client and return evidence.

    The callback is the only side-effect boundary. A real controller must bind
    it to the target Worker Cluster client after independently checking tenant,
    authorization, and target-cluster identity.
    """
    manifest = plan_kagent_agent(claim, now=now)
    observed = apply_manifest(manifest)
    if not isinstance(observed, dict):
        raise ClaimRejected("kagent apply result must be an object")
    status = observed.get("status") if isinstance(observed.get("status"), dict) else {}
    return {
        "apiVersion": "agents.openkubes.io/v1alpha1",
        "kind": "AgentDeployment",
        "metadata": claim["metadata"],
        "spec": claim["spec"],
        "status": {
            "readiness": status.get("readiness", "Unknown"),
            "observedGeneration": status.get("observedGeneration"),
            "evidenceRef": f"agent-deploy/{claim['metadata']['namespace']}/{claim['metadata']['name']}",
        },
    }
