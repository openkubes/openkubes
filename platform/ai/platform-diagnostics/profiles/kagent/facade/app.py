"""
Diagnostics facade — OpenAPI -> kagent shim (Profile A, OK-92).

Implements the three functions of the Read-Only Platform Diagnostics Contract
(ADR-Platform-021) and translates each into an invocation of the kagent
`openkubes-platform-agent`, shaping the result into the normative schema.

SKELETON: HTTP surface + schema + config are real and schema-valid. The kagent
call and the agent-output -> schema mapping are marked TODO — they need the live
kagent endpoint (OK-14 finding) and a couple of prompt/response iterations.
Until then the endpoints return schema-valid STUB results so consumers and the
schema-level contract tests (1/3/5/6) can run.

Read-only by construction: this process holds no kube credentials and exposes no
write path. `recommended_next_steps` are human actions; nothing is executed.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# ── config (Provider Values via env; see README) ─────────────────────────────
KAGENT_BASE_URL = os.getenv("KAGENT_BASE_URL", "http://kagent.kagent.svc.cluster.local:8083")
KAGENT_AGENT = os.getenv("KAGENT_AGENT", "openkubes-platform-agent")
KAGENT_TOKEN = os.getenv("KAGENT_TOKEN")
PROVIDER_NAME = os.getenv("PROVIDER_NAME", "kagent")

# Provider capability declaration (ADR-021): Talos vs RKE2 is a capability delta,
# NEVER a contract delta. Defaults reflect a Talos provider (no host shell/journal).
DEFAULT_CAPS = {
    "workload_events": True,
    "workload_logs": True,
    "cilium_diagnostics": True,
    "host_journal": False,   # Talos
    "node_shell": False,     # Talos
}
PROVIDER_CAPS = json.loads(os.getenv("PROVIDER_CAPS", json.dumps(DEFAULT_CAPS)))

app = FastAPI(
    title="OpenKubes Read-Only Platform Diagnostics Contract",
    version="1.0.0-draft",
    description="Profile A (kagent) provider. Implements ADR-Platform-021.",
)


# ── schema (mirrors contract/openapi.yaml) ───────────────────────────────────
class Confidence(str, Enum):
    low = "low"; medium = "medium"; high = "high"


class CounterEvidence(str, Enum):
    found = "found"; none_found = "none_found"; not_checked = "not_checked"


class EvidenceStatus(str, Enum):
    available = "available"; unavailable = "unavailable"; partial = "partial"


class RankedHypothesis(BaseModel):
    hypothesis: str
    confidence: Confidence
    evidence_refs: list[str] = []
    contradicting_evidence_refs: list[str] = []
    counter_evidence_status: CounterEvidence


class EvidenceRef(BaseModel):
    type: str
    source: str
    status: EvidenceStatus
    reason: Optional[str] = None            # MANDATORY when status != available
    uri: Optional[str] = None               # reference only — never a payload/secret
    collected_at: Optional[datetime] = None


class InvestigateWorkloadInput(BaseModel):
    cluster: str                            # logical name, not an endpoint
    namespace: str
    workload: str
    time_range: str = "PT1H"


class WorkloadInvestigation(BaseModel):
    summary: str
    symptoms: list[str] = []
    evidence: list[EvidenceRef] = []
    probable_causes: list[RankedHypothesis] = []
    recommended_next_steps: list[str] = []   # human actions; never executed
    references: list[str] = []
    provider_capabilities: dict[str, bool] = Field(default_factory=lambda: PROVIDER_CAPS)


class GetPlatformHealthInput(BaseModel):
    clusters: list[str] = []


class ClusterHealth(BaseModel):
    cluster: str
    status: str
    summary: Optional[str] = None
    signals: list[str] = []
    provider_capabilities: dict[str, bool] = Field(default_factory=lambda: PROVIDER_CAPS)


class PlatformHealth(BaseModel):
    generated_at: datetime
    clusters: list[ClusterHealth] = []


class CollectEvidenceInput(BaseModel):
    cluster: str
    namespace: str
    workload: str
    time_range: str = "PT1H"
    evidence_types: list[str] = []


class EvidenceBundle(BaseModel):
    cluster: str
    collected_at: datetime
    evidence: list[EvidenceRef] = []
    provider_capabilities: dict[str, bool] = Field(default_factory=lambda: PROVIDER_CAPS)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── kagent invocation (TODO: wire to the live endpoint) ──────────────────────
async def invoke_agent(function: str, payload: dict) -> dict:
    """Invoke openkubes-platform-agent with a FUNCTION tag; return its raw output.

    TODO(OK-92): confirm kagent's invocation API from the OK-14 evaluation
    (A2A `POST /api/.../invoke` vs. an OpenAI-compatible `/v1/chat/completions`
    surface) and parse the agent's structured reply. The agent is prompted
    (see agents/openkubes-platform-agent.yaml) to supply ranked hypotheses with
    counter_evidence_status and reference-only evidence; map that reply onto the
    pydantic models below. Keep the mapping here so consumers never see kagent.
    """
    headers = {"Content-Type": "application/json"}
    if KAGENT_TOKEN:
        headers["Authorization"] = f"Bearer {KAGENT_TOKEN}"
    request = {"agent": KAGENT_AGENT, "function": function, "input": payload}
    # NOTE: URL/shape is a placeholder pending the OK-14 finding.
    url = f"{KAGENT_BASE_URL}/api/agents/{KAGENT_AGENT}/invoke"
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, headers=headers, json=request)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:  # skeleton: surface as unavailable evidence, not a 500
        return {"_stub": True, "_error": str(exc)}


def _stub_unavailable(reason: str) -> EvidenceRef:
    return EvidenceRef(type="agent", source=PROVIDER_NAME,
                       status=EvidenceStatus.unavailable, reason=reason,
                       collected_at=_now())


# ── the three contract functions ─────────────────────────────────────────────
@app.post("/v1/get_platform_health", response_model=PlatformHealth,
          operation_id="get_platform_health")
async def get_platform_health(body: GetPlatformHealthInput) -> PlatformHealth:
    raw = await invoke_agent("get_platform_health", body.model_dump())
    if raw.get("_stub"):
        # schema-valid stub until kagent is wired
        clusters = body.clusters or ["ok-ai"]
        return PlatformHealth(
            generated_at=_now(),
            clusters=[ClusterHealth(cluster=c, status="unknown",
                                    summary="stub: kagent not yet wired (OK-92)",
                                    signals=[]) for c in clusters],
        )
    raise HTTPException(501, "agent-output mapping not implemented (OK-92 TODO)")


@app.post("/v1/investigate_workload", response_model=WorkloadInvestigation,
          operation_id="investigate_workload")
async def investigate_workload(body: InvestigateWorkloadInput) -> WorkloadInvestigation:
    raw = await invoke_agent("investigate_workload", body.model_dump())
    if raw.get("_stub"):
        return WorkloadInvestigation(
            summary=f"stub: would investigate {body.workload} in "
                    f"{body.cluster}/{body.namespace} (kagent not yet wired, OK-92)",
            symptoms=[],
            evidence=[_stub_unavailable("kagent invocation not implemented (OK-92 TODO)")],
            probable_causes=[],   # empty is valid; a stub must not invent hypotheses
            recommended_next_steps=[],
        )
    raise HTTPException(501, "agent-output mapping not implemented (OK-92 TODO)")


@app.post("/v1/collect_diagnostic_evidence", response_model=EvidenceBundle,
          operation_id="collect_diagnostic_evidence")
async def collect_diagnostic_evidence(body: CollectEvidenceInput) -> EvidenceBundle:
    raw = await invoke_agent("collect_diagnostic_evidence", body.model_dump())
    if raw.get("_stub"):
        return EvidenceBundle(
            cluster=body.cluster, collected_at=_now(),
            evidence=[_stub_unavailable("kagent invocation not implemented (OK-92 TODO)")],
        )
    raise HTTPException(501, "agent-output mapping not implemented (OK-92 TODO)")


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict:
    return {"status": "ok", "kagent": KAGENT_BASE_URL, "agent": KAGENT_AGENT}
