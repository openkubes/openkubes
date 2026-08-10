"""Generated from ../openapi.yaml; do not edit by hand."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


Invoker = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


def register_tools(mcp: Any, invoke: Invoker) -> None:
    # Source: openapi.yaml
    @mcp.tool()
    async def get_platform_health(clusters: list[str] | None = None) -> dict[str, Any]:
        """Cross-cluster/platform health snapshot. Forcing consumer — incident diagnostic workflow."""
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
        """Standardized diagnostic report for one workload. Forcing consumer — incident diagnostic workflow."""
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
        """Raw evidence bundle without hypothesis generation. Public because it supports incident handoff, audit, and offline expert review WITHOUT requiring hypothesis generation — a consumer-forced capability, not a technical decomposition of the provider."""
        body: dict[str, Any] = {}
        body["cluster"] = cluster
        body["namespace"] = namespace
        body["workload"] = workload
        body["time_range"] = time_range
        if evidence_types is not None:
            body["evidence_types"] = evidence_types
        return await invoke("/v1/collect_diagnostic_evidence", body)
