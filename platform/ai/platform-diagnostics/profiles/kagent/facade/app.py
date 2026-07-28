"""
Diagnostics facade — OpenAPI -> kagent shim (Profile A, OK-92).

Implements the three functions of the Read-Only Platform Diagnostics Contract
(ADR-Platform-021) and translates each into an A2A invocation of the kagent
`openkubes-platform-agent`, then maps the agent's reply onto the normative schema.

Wire format (confirmed against ok-ai, 2026-07-27):
  * A2A JSON-RPC 2.0, method "message/send", at
    {KAGENT_BASE_URL}/api/a2a/{KAGENT_NAMESPACE}/{KAGENT_AGENT}
  * response: result.status.state == "completed";
    the agent's answer is the text of result.artifacts[*].parts[* kind=text].

Read-only by construction: this process holds no kube credentials (cluster access
lives only in the scoped tools server's SA). recommended_next_steps are human
actions; nothing is executed.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from urllib.parse import quote

import httpx
from fastapi import FastAPI
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel, Field

# ── config (Provider Values via env; see README) ─────────────────────────────
KAGENT_BASE_URL = os.getenv("KAGENT_BASE_URL", "http://kagent-controller.kagent.svc.cluster.local:8083")
KAGENT_NAMESPACE = os.getenv("KAGENT_NAMESPACE", "platform-diagnostics")
KAGENT_AGENT = os.getenv("KAGENT_AGENT", "openkubes-platform-agent")
KAGENT_TOKEN = os.getenv("KAGENT_TOKEN")
KAGENT_TOOLS_URL = os.getenv(
    "KAGENT_TOOLS_URL",
    "http://platform-diagnostics-tools.platform-diagnostics.svc.cluster.local:8084/mcp",
)
PROVIDER_NAME = os.getenv("PROVIDER_NAME", "kagent")
DEFAULT_CLUSTER = os.getenv("DEFAULT_CLUSTER", "ok-ai")
AGENT_TIMEOUT = float(os.getenv("AGENT_TIMEOUT_SECONDS", "300"))

# Provider capability declaration (ADR-021). Talos defaults (no host shell/journal).
DEFAULT_CAPS = {
    "workload_events": True, "workload_logs": True, "cilium_diagnostics": True,
    "host_journal": False, "node_shell": False,
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
    confidence: Confidence = Confidence.low
    evidence_refs: list[str] = []
    contradicting_evidence_refs: list[str] = []
    counter_evidence_status: CounterEvidence = CounterEvidence.not_checked


class EvidenceRef(BaseModel):
    type: str
    source: str
    status: EvidenceStatus = EvidenceStatus.available
    reason: Optional[str] = None
    uri: Optional[str] = None
    collected_at: Optional[datetime] = None


class InvestigateWorkloadInput(BaseModel):
    cluster: str
    namespace: str
    workload: str
    time_range: str = "PT1H"


class WorkloadInvestigation(BaseModel):
    summary: str
    symptoms: list[str] = []
    evidence: list[EvidenceRef] = []
    probable_causes: list[RankedHypothesis] = []
    recommended_next_steps: list[str] = []
    references: list[str] = []
    provider_capabilities: dict[str, bool] = Field(default_factory=lambda: PROVIDER_CAPS)


class GetPlatformHealthInput(BaseModel):
    clusters: list[str] = []


class ClusterHealth(BaseModel):
    cluster: str
    status: str = "unknown"
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


class AgentError(Exception):
    """Agent unreachable or returned a non-completed task."""


# ── kagent A2A invocation ────────────────────────────────────────────────────
async def invoke_agent(text: str) -> str:
    """Send `text` to openkubes-platform-agent over A2A; return the agent's reply.

    Raises AgentError if the agent is unreachable or the task did not complete.
    """
    headers = {"Content-Type": "application/json"}
    if KAGENT_TOKEN:
        headers["Authorization"] = f"Bearer {KAGENT_TOKEN}"
    url = f"{KAGENT_BASE_URL}/api/a2a/{KAGENT_NAMESPACE}/{KAGENT_AGENT}"
    mid = uuid.uuid4().hex
    rpc = {
        "jsonrpc": "2.0", "id": mid, "method": "message/send",
        "params": {"message": {
            "role": "user", "messageId": mid,
            "parts": [{"kind": "text", "text": text}],
        }},
    }
    try:
        async with httpx.AsyncClient(timeout=AGENT_TIMEOUT) as client:
            resp = await client.post(url, headers=headers, json=rpc)
            resp.raise_for_status()
            body = resp.json()
    except Exception as exc:
        raise AgentError(f"A2A call failed: {exc}") from exc

    if "error" in body:
        raise AgentError(f"A2A error: {body['error']}")
    result = body.get("result", {})
    state = (result.get("status") or {}).get("state")
    # Only hard-fail on error states. "input-required" (the agent asked a question
    # instead of completing) is tolerated IF it still produced artifact text; the
    # prompt below tells the agent not to ask, so this is a safety net.
    if state in ("failed", "rejected", "canceled", "error"):
        raise AgentError(f"agent task state: {state}")
    # answer = concatenated text parts of the produced artifacts
    parts_text = [
        p.get("text", "")
        for art in result.get("artifacts", [])
        for p in art.get("parts", [])
        if p.get("kind") == "text"
    ]
    text_out = "\n".join(t for t in parts_text if t).strip()
    if not text_out:
        raise AgentError(f"agent returned no artifact (state={state})")
    return text_out


async def _call_read_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Call the scoped read-only kagent toolserver and decode its JSON result."""
    try:
        async with streamable_http_client(KAGENT_TOOLS_URL) as streams:
            read_stream, write_stream = streams[0], streams[1]
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments)
    except Exception as exc:
        raise AgentError(f"read tool {name} failed: {exc}") from exc

    if result.isError:
        raise AgentError(f"read tool {name} returned an error")
    text = "\n".join(
        block.text for block in result.content
        if getattr(block, "type", None) == "text"
    ).strip()
    if not text:
        raise AgentError(f"read tool {name} returned no JSON")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise AgentError(f"read tool {name} returned invalid JSON") from exc


def _pod_matches_workload(pod: dict[str, Any], workload: str) -> bool:
    metadata = pod.get("metadata") or {}
    name = str(metadata.get("name", ""))
    prefix = f"{workload}-"
    if name == workload or name.startswith(prefix):
        return True
    owners = metadata.get("ownerReferences") or []
    if any(
        str(owner.get("name", "")) == workload
        or str(owner.get("name", "")).startswith(prefix)
        for owner in owners if isinstance(owner, dict)
    ):
        return True
    labels = metadata.get("labels") or {}
    return any(
        str(value) == workload or str(value).startswith(prefix)
        for value in labels.values()
    )


async def _get_workload_pods(body: InvestigateWorkloadInput) -> list[dict[str, Any]]:
    data = await _call_read_tool("k8s_get_resources", {
        "resource_type": "pods",
        "namespace": body.namespace,
        "output": "json",
    })
    items = data.get("items", []) if isinstance(data, dict) else []
    return [
        pod for pod in items
        if isinstance(pod, dict) and _pod_matches_workload(pod, body.workload)
    ]


def _pod_inventory_report(
    body: InvestigateWorkloadInput,
    pods: list[dict[str, Any]],
) -> Optional[WorkloadInvestigation]:
    """Return a deterministic report when inventory proves no current pod fault."""
    encoded_cluster = quote(body.cluster, safe="")
    encoded_namespace = quote(body.namespace, safe="")
    encoded_workload = quote(body.workload, safe="")
    query_uri = (
        f"k8s://{encoded_cluster}/namespaces/{encoded_namespace}/pods"
        f"?workload={encoded_workload}"
    )
    evidence = [EvidenceRef(
        type="workload-pod-inventory",
        source="kubernetes-api",
        status=EvidenceStatus.available,
        reason=f"matched_pods={len(pods)}",
        uri=query_uri,
        collected_at=_now(),
    )]

    ready_count = 0
    restart_count = 0
    all_running = True
    for pod in pods:
        metadata = pod.get("metadata") or {}
        status = pod.get("status") or {}
        container_statuses = status.get("containerStatuses") or []
        ready = bool(container_statuses) and all(
            bool(container.get("ready")) for container in container_statuses
        )
        restarts = sum(
            int(container.get("restartCount", 0) or 0)
            for container in container_statuses
        )
        phase = str(status.get("phase", "Unknown"))
        if ready:
            ready_count += 1
        restart_count += restarts
        all_running = all_running and phase == "Running"
        pod_name = str(metadata.get("name", "unknown"))
        evidence.append(EvidenceRef(
            type="pod-status",
            source="kubernetes-api",
            status=EvidenceStatus.available,
            reason=(
                f"phase={phase}; ready={str(ready).lower()}; "
                f"cumulative_restarts={restarts}"
            ),
            uri=(
                f"k8s://{encoded_cluster}/namespaces/{encoded_namespace}/pods/"
                f"{quote(pod_name, safe='')}"
            ),
            collected_at=_now(),
        ))

    summary = (
        f"Observed {len(pods)} pod(s) matching workload {body.workload} in "
        f"{body.cluster}/{body.namespace}: {ready_count} Ready, "
        f"{len(pods) - ready_count} not Ready, "
        f"{restart_count} cumulative container restart(s)."
    )
    if not pods:
        return WorkloadInvestigation(
            summary=summary,
            symptoms=[f"No pods currently match workload {body.workload}."],
            evidence=evidence,
        )
    if all_running and ready_count == len(pods) and restart_count == 0:
        return WorkloadInvestigation(
            summary=summary + " No current pod readiness or restart symptom was observed.",
            evidence=evidence,
        )
    return None


def _extract_json(text: str) -> Optional[dict]:
    """Pull a JSON object out of an LLM reply (tolerates ```json fences / prose)."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = m.group(1) if m else None
    if candidate is None:
        i, j = text.find("{"), text.rfind("}")
        candidate = text[i : j + 1] if i != -1 and j > i else None
    if not candidate:
        return None
    try:
        val = json.loads(candidate)
        return val if isinstance(val, dict) else None
    except json.JSONDecodeError:
        return None


def _coerce_evidence(items: Any) -> list[EvidenceRef]:
    out: list[EvidenceRef] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        try:
            out.append(EvidenceRef(
                type=str(it.get("type", "unknown")),
                source=str(it.get("source", PROVIDER_NAME)),
                status=EvidenceStatus(it.get("status", "available")),
                reason=it.get("reason"),
                uri=it.get("uri"),
                collected_at=_now(),
            ))
        except Exception:
            continue
    return out


def _coerce_hypotheses(items: Any) -> list[RankedHypothesis]:
    out: list[RankedHypothesis] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        try:
            out.append(RankedHypothesis(
                hypothesis=str(it.get("hypothesis", "")).strip() or "(unspecified)",
                confidence=Confidence(str(it.get("confidence", "low")).lower()),
                evidence_refs=list(it.get("evidence_refs", []) or []),
                contradicting_evidence_refs=list(it.get("contradicting_evidence_refs", []) or []),
                # ADR-021: absence of sought counter-evidence is not_checked, not silence.
                counter_evidence_status=CounterEvidence(
                    str(it.get("counter_evidence_status", "not_checked")).lower()),
            ))
        except Exception:
            continue
    return out


def _investigation_validation_errors(
    symptoms: list[str],
    evidence: list[EvidenceRef],
    hypotheses: list[RankedHypothesis],
) -> list[str]:
    """Reject LLM claims that are not linked to retrievable evidence.

    The facade is the trust boundary: schema-valid JSON from an agent is not
    automatically factual. A finalized diagnosis may claim symptoms or causes
    only when its available evidence has a URI and every hypothesis references
    one of those URIs. ADR-021 also forbids finalized hypotheses whose
    counter-evidence was never checked.
    """
    errors: list[str] = []
    available_uris = {
        item.uri for item in evidence
        if item.status == EvidenceStatus.available and item.uri
    }

    missing_uri = [
        item.type for item in evidence
        if item.status == EvidenceStatus.available and not item.uri
    ]
    if missing_uri:
        errors.append(
            "available evidence missing uri: " + ", ".join(sorted(set(missing_uri)))
        )

    if (symptoms or hypotheses) and not available_uris:
        errors.append("diagnostic claims have no retrievable evidence")

    for index, hypothesis in enumerate(hypotheses, start=1):
        if not hypothesis.evidence_refs:
            errors.append(f"hypothesis {index} has no evidence_refs")
        unknown_refs = [
            ref for ref in hypothesis.evidence_refs
            if ref not in available_uris
        ]
        if unknown_refs:
            errors.append(f"hypothesis {index} references unknown evidence")
        unknown_counter_refs = [
            ref for ref in hypothesis.contradicting_evidence_refs
            if ref not in available_uris
        ]
        if unknown_counter_refs:
            errors.append(
                f"hypothesis {index} references unknown counter-evidence"
            )
        if hypothesis.counter_evidence_status == CounterEvidence.not_checked:
            errors.append(f"hypothesis {index} did not check counter-evidence")

    return errors


# ── prompt builders (ask the agent for STRICT JSON in the contract shape) ────
def _instruct(function: str, payload: dict, shape: str) -> str:
    return (
        f"FUNCTION: {function}\n"
        f"INPUT: {json.dumps(payload)}\n\n"
        "You are read-only. Perform the diagnosis using your read tools, then respond\n"
        "with ONLY a single JSON object (no prose, no markdown fences) of EXACTLY this shape:\n"
        f"{shape}\n"
        "Rules:\n"
        "- Do NOT ask clarifying questions or request more input. Assess with the tools\n"
        "  available and return the JSON regardless of what is missing.\n"
        "- Reference evidence by source (never paste raw logs or secrets).\n"
        "- Every probable cause needs a counter_evidence_status of found|none_found|not_checked.\n"
        "- recommended_next_steps are actions for a human.\n"
        "- Events and pod logs ARE available via your read-only tools (k8s_get_events,\n"
        "  k8s_get_pod_logs) — use them. Only host journal and node shell are unsupported;\n"
        "  mark ONLY those as unavailable evidence."
    )


_SHAPE_INVESTIGATE = (
    '{"summary":str,"symptoms":[str],'
    '"evidence":[{"type":str,"source":str,"status":"available|unavailable|partial",'
    '"reason":str,"uri":str}],'
    '"probable_causes":[{"hypothesis":str,"confidence":"low|medium|high",'
    '"evidence_refs":[str],"contradicting_evidence_refs":[str],'
    '"counter_evidence_status":"found|none_found|not_checked"}],'
    '"recommended_next_steps":[str],"references":[str]}'
)
_SHAPE_HEALTH = (
    '{"clusters":[{"cluster":str,"status":"healthy|degraded|unavailable|unknown",'
    '"summary":str,"signals":[str]}]}'
)
_SHAPE_EVIDENCE = (
    '{"evidence":[{"type":str,"source":str,"status":"available|unavailable|partial",'
    '"reason":str,"uri":str}]}'
)


# ── the three contract functions ─────────────────────────────────────────────
@app.post("/v1/get_platform_health", response_model=PlatformHealth,
          operation_id="get_platform_health")
async def get_platform_health(body: GetPlatformHealthInput) -> PlatformHealth:
    clusters = body.clusters or [DEFAULT_CLUSTER]
    try:
        text = await invoke_agent(_instruct("get_platform_health", body.model_dump(), _SHAPE_HEALTH))
    except AgentError as e:
        return PlatformHealth(generated_at=_now(), clusters=[
            ClusterHealth(cluster=c, status="unknown",
                          summary=f"provider unavailable: {e}") for c in clusters])
    data = _extract_json(text) or {}
    out = []
    for c in data.get("clusters", []) if isinstance(data, dict) else []:
        if isinstance(c, dict) and c.get("cluster"):
            out.append(ClusterHealth(
                cluster=str(c["cluster"]), status=str(c.get("status", "unknown")),
                summary=c.get("summary"), signals=list(c.get("signals", []) or [])))
    if not out:  # agent answered but not as parseable JSON
        out = [ClusterHealth(cluster=c, status="unknown", summary=text[:500]) for c in clusters]
    return PlatformHealth(generated_at=_now(), clusters=out)


@app.post("/v1/investigate_workload", response_model=WorkloadInvestigation,
          operation_id="investigate_workload")
async def investigate_workload(body: InvestigateWorkloadInput) -> WorkloadInvestigation:
    try:
        pods = await _get_workload_pods(body)
    except AgentError as e:
        return WorkloadInvestigation(
            summary=(
                f"provider unavailable for {body.workload} in "
                f"{body.cluster}/{body.namespace}"
            ),
            evidence=[EvidenceRef(
                type="workload-pod-inventory",
                source=PROVIDER_NAME,
                status=EvidenceStatus.unavailable,
                reason=str(e),
                collected_at=_now(),
            )],
        )
    inventory_report = _pod_inventory_report(body, pods)
    if inventory_report is not None:
        return inventory_report

    try:
        text = await invoke_agent(_instruct("investigate_workload", body.model_dump(), _SHAPE_INVESTIGATE))
    except AgentError as e:
        return WorkloadInvestigation(
            summary=f"provider unavailable for {body.workload} in {body.cluster}/{body.namespace}",
            evidence=[EvidenceRef(type="agent", source=PROVIDER_NAME,
                                  status=EvidenceStatus.unavailable, reason=str(e),
                                  collected_at=_now())])
    data = _extract_json(text)
    if not data:  # reached the agent but no parseable JSON — degrade gracefully, stay schema-valid
        return WorkloadInvestigation(
            summary=text[:1000],
            evidence=[EvidenceRef(type="agent", source=PROVIDER_NAME,
                                  status=EvidenceStatus.partial,
                                  reason="agent reply was not structured JSON",
                                  collected_at=_now())])
    symptoms = list(data.get("symptoms", []) or [])
    evidence = _coerce_evidence(data.get("evidence"))
    hypotheses = _coerce_hypotheses(data.get("probable_causes"))
    validation_errors = _investigation_validation_errors(
        symptoms, evidence, hypotheses
    )
    if validation_errors:
        return WorkloadInvestigation(
            summary=(
                f"provider returned unverified diagnostic output for "
                f"{body.workload} in {body.cluster}/{body.namespace}"
            ),
            evidence=[EvidenceRef(
                type="agent-output-validation",
                source=PROVIDER_NAME,
                status=EvidenceStatus.unavailable,
                reason="; ".join(validation_errors),
                collected_at=_now(),
            )],
        )
    return WorkloadInvestigation(
        summary=str(data.get("summary", "")).strip() or text[:500],
        symptoms=symptoms,
        evidence=evidence,
        probable_causes=hypotheses,
        recommended_next_steps=list(data.get("recommended_next_steps", []) or []),
        references=list(data.get("references", []) or []))


@app.post("/v1/collect_diagnostic_evidence", response_model=EvidenceBundle,
          operation_id="collect_diagnostic_evidence")
async def collect_diagnostic_evidence(body: CollectEvidenceInput) -> EvidenceBundle:
    try:
        text = await invoke_agent(_instruct("collect_diagnostic_evidence", body.model_dump(), _SHAPE_EVIDENCE))
    except AgentError as e:
        return EvidenceBundle(cluster=body.cluster, collected_at=_now(), evidence=[
            EvidenceRef(type="agent", source=PROVIDER_NAME, status=EvidenceStatus.unavailable,
                        reason=str(e), collected_at=_now())])
    data = _extract_json(text) or {}
    ev = _coerce_evidence(data.get("evidence")) if isinstance(data, dict) else []
    if not ev:
        ev = [EvidenceRef(type="agent", source=PROVIDER_NAME, status=EvidenceStatus.partial,
                          reason="agent reply was not structured JSON", collected_at=_now())]
    return EvidenceBundle(cluster=body.cluster, collected_at=_now(), evidence=ev)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict:
    return {"status": "ok", "kagent": KAGENT_BASE_URL, "agent": KAGENT_AGENT}
