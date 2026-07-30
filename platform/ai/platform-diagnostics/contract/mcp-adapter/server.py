"""
MCP adapter for the Read-Only Platform Diagnostics Contract (ADR-021).

A thin, agent-facing MCP server derived from the OpenAPI Draft implementation
scaffold: it exposes the three contract functions as MCP tools and forwards each
to the HTTP contract (the facade). It holds NO Kubernetes credentials — it only
speaks to the facade, which speaks to kagent's read-only provider. Consumers
(OpenClaw today, others later) register this over MCP; normative OpenAPI
finalization remains in OK-89/OK-90.

Transport: streamable-http at /mcp (matches OpenClaw `mcp add --transport
streamable-http` and kagent's own tool server).

The tool docstrings ARE the descriptions the agent uses to decide when to call
them — keep them accurate.
"""
from __future__ import annotations

import os
import httpx
from mcp.server.fastmcp import FastMCP

FACADE_URL = os.getenv(
    "FACADE_URL",
    "http://platform-diagnostics.platform-diagnostics.svc.cluster.local:8080",
)
# A real diagnosis runs an LLM + read-only tool calls behind the contract (30-120s).
HTTP_TIMEOUT = float(os.getenv("FACADE_TIMEOUT_SECONDS", "300"))

mcp = FastMCP(
    "platform-diagnostics",
    host=os.getenv("HOST", "0.0.0.0"),
    port=int(os.getenv("PORT", "8080")),
)


async def _call(path: str, body: dict) -> dict:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(f"{FACADE_URL}/v1/{path}", json=body)
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def get_platform_health(clusters: list[str] | None = None) -> dict:
    """Read-only cross-cluster/platform health snapshot.

    Use when asked about overall cluster or platform health. `clusters` is an
    optional list of logical cluster names; omit for all known clusters. Returns
    the ADR-021 PlatformHealth object (status, signals, provider_capabilities).
    """
    return await _call("get_platform_health", {"clusters": clusters or []})


@mcp.tool()
async def investigate_workload(
    cluster: str, namespace: str, workload: str, time_range: str = "PT1H"
) -> dict:
    """Read-only diagnostic report for ONE workload (pod/deployment/etc).

    Use when asked why a workload is failing, unhealthy, crashing, or degraded.
    `cluster` is a logical name (not an endpoint). `time_range` is an ISO-8601
    duration (default PT1H). Returns the ADR-021 WorkloadInvestigation object
    (summary, symptoms, evidence refs, ranked probable_causes with
    counter_evidence_status, recommended_next_steps). Read-only: it never changes
    cluster state; next steps are for a human.
    """
    return await _call("investigate_workload", {
        "cluster": cluster, "namespace": namespace,
        "workload": workload, "time_range": time_range,
    })


@mcp.tool()
async def collect_diagnostic_evidence(
    cluster: str, namespace: str, workload: str, time_range: str = "PT1H"
) -> dict:
    """Read-only raw evidence bundle (references only) for one workload.

    Use for incident handoff, audit, or offline review when you want evidence
    WITHOUT hypothesis generation. Returns the ADR-021 EvidenceBundle (evidence
    references, never embedded payloads or secrets).
    """
    return await _call("collect_diagnostic_evidence", {
        "cluster": cluster, "namespace": namespace,
        "workload": workload, "time_range": time_range,
    })


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
