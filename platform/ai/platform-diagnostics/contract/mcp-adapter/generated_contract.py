"""Generated from ../openapi.yaml; do not edit by hand."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


REQUEST_ID_HEADER = 'X-Request-Id'
INVOCATION_ID_HEADER = 'X-Invocation-Id'


Invoker = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


def register_tools(mcp: Any, invoke: Invoker) -> None:
    # Source: openapi.yaml
    @mcp.tool()
    async def get_platform_health(clusters: list[str] | None = None) -> dict[str, Any]:
        """Get a cross-cluster platform health snapshot. Returns health for the requested logical cluster names. An empty request includes all clusters known to the provider. Cluster values are logical names, never API endpoints or kubeconfig references."""
        body: dict[str, Any] = {}
        if clusters is not None:
            body["clusters"] = clusters
        return await invoke("/v1/get_platform_health", body)

    @mcp.tool()
    async def investigate_workload(
        cluster: str,
        namespace: str,
        workload: str,
        time_range: str = 'PT1H',
    ) -> dict[str, Any]:
        """Investigate one workload. Returns a finalized diagnostic result grounded in referenced evidence. Recommended next steps are human actions only and are never executed by the provider. Every returned hypothesis has completed a counter-evidence check; `not_checked` is invalid in a successful response."""
        body: dict[str, Any] = {}
        body["cluster"] = cluster
        body["namespace"] = namespace
        body["workload"] = workload
        body["time_range"] = time_range
        return await invoke("/v1/investigate_workload", body)

    @mcp.tool()
    async def collect_diagnostic_evidence(
        cluster: str,
        namespace: str,
        workload: str,
        time_range: str = 'PT1H',
        evidence_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Collect evidence without generating hypotheses. Returns evidence references for incident handoff, audit, or offline expert review. Raw logs, events, credentials, and secret values remain at their sources. For every explicitly requested unsupported evidence type, the response contains an `unavailable` EvidenceRef with a reason; silent omission is not conformant."""
        body: dict[str, Any] = {}
        body["cluster"] = cluster
        body["namespace"] = namespace
        body["workload"] = workload
        body["time_range"] = time_range
        if evidence_types is not None:
            body["evidence_types"] = evidence_types
        return await invoke("/v1/collect_diagnostic_evidence", body)
