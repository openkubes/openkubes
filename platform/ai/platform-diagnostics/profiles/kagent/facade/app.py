"""
Diagnostics facade — OpenAPI -> kagent shim (Profile A, OK-92).

Implements the three functions of the Read-Only Platform Diagnostics Contract
(ADR-Platform-021) and translates each into an A2A invocation of the kagent
`openkubes-platform-agent`, then maps the agent's reply onto the normative
ADR-021 Phase-1 OpenAPI contract.

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
import hashlib
import logging
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, ClassVar, Optional
from urllib.parse import quote

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.json_schema import GetJsonSchemaHandler

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
DIAGNOSTICS_BEARER_TOKEN = os.getenv("DIAGNOSTICS_BEARER_TOKEN", "").strip()
LOGGER = logging.getLogger("platform-diagnostics.invocation")

# Provider capability declaration (ADR-021). Talos defaults (no host shell/journal).
DEFAULT_CAPS = {
    "workload_events": True, "workload_logs": True, "cilium_diagnostics": True,
    "host_journal": False, "node_shell": False,
}
PROVIDER_CAPS = json.loads(os.getenv("PROVIDER_CAPS", json.dumps(DEFAULT_CAPS)))

app = FastAPI(
    title="OpenKubes Read-Only Platform Diagnostics Contract",
    version="1.1.0",
    description="Profile A (kagent) provider. Implements ADR-Platform-021.",
)


def _error_response(request: Request, status: int, code: str, message: str) -> JSONResponse:
    invocation_id = getattr(request.state, "invocation_id", None)
    payload = {"code": code, "message": message}
    if invocation_id:
        payload["invocation_id"] = invocation_id
    return JSONResponse(status_code=status, content=payload)


@app.middleware("http")
async def invocation_correlation(request: Request, call_next):
    request.state.invocation_id = f"inv-{uuid.uuid4().hex}"
    response = await call_next(request)
    response.headers["X-Invocation-Id"] = request.state.invocation_id
    return response


@app.exception_handler(HTTPException)
async def contract_http_error(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    return _error_response(
        request,
        exc.status_code,
        str(detail.get("code", "request_failed")),
        str(detail.get("message", exc.detail)),
    )


@app.exception_handler(RequestValidationError)
async def contract_validation_error(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return _error_response(
        request,
        422,
        "invalid_request",
        "request does not conform to the operation input schema",
    )


async def require_consumer_identity(
    request: Request,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    request_id: Optional[str] = Header(
        default=None,
        alias="X-Request-Id",
        min_length=1,
        max_length=128,
    ),
) -> None:
    if not DIAGNOSTICS_BEARER_TOKEN:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "provider_unavailable",
                "message": "consumer authentication is not configured",
            },
        )
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token or not secrets.compare_digest(
        token, DIAGNOSTICS_BEARER_TOKEN
    ):
        LOGGER.warning(
            "diagnostics invocation rejected invocation_id=%s operation=%s "
            "request_id=%s",
            request.state.invocation_id,
            request.url.path,
            request_id or "-",
        )
        raise HTTPException(
            status_code=401,
            detail={
                "code": "unauthorized",
                "message": "a valid consumer bearer identity is required",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    consumer_id = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    LOGGER.info(
        "diagnostics invocation accepted invocation_id=%s operation=%s "
        "consumer_id=%s request_id=%s timestamp=%s",
        request.state.invocation_id,
        request.url.path,
        consumer_id,
        request_id or "-",
        _now().isoformat(),
    )


# ── schema (mirrors contract/openapi.yaml) ───────────────────────────────────
class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContractResult(ContractModel):
    """A response model whose *published* schema matches the normative contract.

    A field with a Python default is optional in the schema Pydantic generates,
    even when the code always populates it and the contract declares it
    required. The provider would then advertise a weaker contract than the one it
    implements, and a consumer or generator reading the published document would
    be told that required fields may be absent. Contract test 1 diffs the
    generated document against the normative file, so the published required set
    is derived from the declared fields rather than from Python defaults.

    ``_contract_optional`` names the fields the contract genuinely leaves
    optional — for EvidenceRef, ``reason`` and ``uri`` are conditional on
    ``status`` and are expressed in the contract with if/then, not with required.
    """

    _contract_optional: ClassVar[frozenset[str]] = frozenset()

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: Any,
        handler: GetJsonSchemaHandler,
    ) -> dict[str, Any]:
        schema = handler.resolve_ref_schema(handler(core_schema))
        properties = schema.get("properties")
        if properties:
            schema["required"] = [
                name for name in properties if name not in cls._contract_optional
            ]
        return schema


class ProviderCapabilities(BaseModel):
    """Normative provider capability declaration (ADR-021).

    Typed rather than a bare mapping: a distribution difference is a capability
    delta, never a contract delta, so the five declared capabilities are part of
    the published surface. Additional boolean capabilities may be introduced
    without a contract change. An incomplete PROVIDER_CAPS now fails at startup
    instead of silently shipping a response that declares nothing.
    """

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={"additionalProperties": {"type": "boolean"}},
    )

    workload_events: bool
    workload_logs: bool
    cilium_diagnostics: bool
    host_journal: bool
    node_shell: bool


# Fails fast if a deployment supplies an incomplete capability declaration.
PROVIDER_CAPABILITIES = ProviderCapabilities(**PROVIDER_CAPS)


class Confidence(str, Enum):
    low = "low"; medium = "medium"; high = "high"


class CounterEvidence(str, Enum):
    found = "found"; none_found = "none_found"; not_checked = "not_checked"


class EvidenceStatus(str, Enum):
    available = "available"; unavailable = "unavailable"; partial = "partial"


class RankedHypothesis(ContractResult):
    hypothesis: str
    confidence: Confidence = Confidence.low
    evidence_refs: list[str] = []
    contradicting_evidence_refs: list[str] = []
    counter_evidence_status: CounterEvidence = CounterEvidence.not_checked


class FinalizedCounterEvidence(str, Enum):
    """Counter-evidence status admissible in a finalized result.

    The contract narrows the enum for a returned hypothesis; the runtime already
    drops unchecked hypotheses, and publishing the wider enum would advertise a
    result shape the provider never returns.
    """

    found = "found"; none_found = "none_found"


class FinalizedRankedHypothesis(RankedHypothesis):
    counter_evidence_status: FinalizedCounterEvidence


class EvidenceRef(ContractResult):
    _contract_optional: ClassVar[frozenset[str]] = frozenset({"reason", "uri"})

    # The contract states the conditional requirement in the schema, so the
    # published document has to state it too. validate_status_fields below
    # enforces it at runtime; without this the provider would enforce a rule it
    # never told anyone about.
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "required": ["status"],
                        "properties": {"status": {"enum": ["unavailable", "partial"]}},
                    },
                    "then": {"required": ["reason"]},
                },
                {
                    "if": {
                        "required": ["status"],
                        "properties": {"status": {"enum": ["available", "partial"]}},
                    },
                    "then": {"required": ["uri"]},
                },
            ]
        },
    )

    id: str = Field(
        default_factory=lambda: f"ev-{uuid.uuid4().hex}",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
        max_length=128,
    )
    type: str
    source: str
    status: EvidenceStatus = EvidenceStatus.available
    reason: Optional[str] = None
    uri: Optional[str] = None
    collected_at: datetime = Field(default_factory=lambda: _now())

    @model_validator(mode="after")
    def validate_status_fields(self) -> "EvidenceRef":
        if self.status in {EvidenceStatus.unavailable, EvidenceStatus.partial}:
            if not self.reason or not self.reason.strip():
                raise ValueError("unavailable or partial evidence requires a reason")
        if self.status in {EvidenceStatus.available, EvidenceStatus.partial}:
            if not self.uri or not self.uri.strip():
                raise ValueError("available or partial evidence requires a uri")
        return self


class InvestigateWorkloadInput(ContractModel):
    cluster: str
    namespace: str
    workload: str
    time_range: str = "PT1H"


class TimeWindow(ContractResult):
    start: datetime
    end: datetime


class WorkloadInvestigation(ContractResult):
    invocation_id: str
    cluster: str
    namespace: str
    workload: str
    generated_at: datetime
    effective_time_range: TimeWindow
    summary: str
    symptoms: list[str] = []
    evidence: list[EvidenceRef] = []
    probable_causes: list[FinalizedRankedHypothesis] = []
    recommended_next_steps: list[str] = []
    references: list[str] = []
    provider_capabilities: ProviderCapabilities = Field(
        default_factory=lambda: PROVIDER_CAPABILITIES.model_copy()
    )


class GetPlatformHealthInput(ContractModel):
    clusters: list[str] = []


class ClusterStatus(str, Enum):
    healthy = "healthy"
    degraded = "degraded"
    unavailable = "unavailable"
    unknown = "unknown"


class ClusterHealth(ContractResult):
    cluster: str
    status: ClusterStatus = ClusterStatus.unknown
    summary: str
    signals: list[str] = []
    provider_capabilities: ProviderCapabilities = Field(
        default_factory=lambda: PROVIDER_CAPABILITIES.model_copy()
    )


class PlatformHealth(ContractResult):
    invocation_id: str
    generated_at: datetime
    clusters: list[ClusterHealth] = []


class CollectDiagnosticEvidenceInput(ContractModel):
    cluster: str
    namespace: str
    workload: str
    time_range: str = "PT1H"
    evidence_types: list[str] = []


class EvidenceBundle(ContractResult):
    invocation_id: str
    cluster: str
    namespace: str
    workload: str
    collected_at: datetime
    effective_time_range: TimeWindow
    evidence: list[EvidenceRef] = []
    provider_capabilities: ProviderCapabilities = Field(
        default_factory=lambda: PROVIDER_CAPABILITIES.model_copy()
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _effective_time_range(time_range: str, end: Optional[datetime] = None) -> TimeWindow:
    end_time = end or _now()
    match = re.fullmatch(
        r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?)?",
        time_range,
    )
    if not match or not any(match.groupdict().values()):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_request",
                "message": "time_range must be a supported ISO-8601 duration",
            },
        )
    duration = timedelta(
        days=int(match.group("days") or 0),
        hours=int(match.group("hours") or 0),
        minutes=int(match.group("minutes") or 0),
    )
    if duration <= timedelta(0):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_request",
                "message": "time_range must be greater than zero",
            },
        )
    return TimeWindow(start=end_time - duration, end=end_time)


def _investigation_context(
    request: Request,
    body: InvestigateWorkloadInput,
    generated_at: Optional[datetime] = None,
) -> dict[str, Any]:
    timestamp = generated_at or _now()
    return {
        "invocation_id": request.state.invocation_id,
        "cluster": body.cluster,
        "namespace": body.namespace,
        "workload": body.workload,
        "generated_at": timestamp,
        "effective_time_range": _effective_time_range(body.time_range, timestamp),
    }


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
    """Call the scoped read-only kagent toolserver and decode its result.

    Resource and event tools return JSON, while pod logs and describe return
    plain text. Preserve plain text so callers can ground diagnoses in it.
    """
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
        raise AgentError(f"read tool {name} returned no content")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


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


def _pod_observation(pod: dict[str, Any]) -> dict[str, Any]:
    """Return only diagnosis-relevant, non-secret pod state for the agent."""
    metadata = pod.get("metadata") or {}
    spec = pod.get("spec") or {}
    status = pod.get("status") or {}
    return {
        "name": str(metadata.get("name", "")),
        "phase": str(status.get("phase", "Unknown")),
        "containers": [
            {
                "name": str(container.get("name", "")),
                "image": str(container.get("image", "")),
            }
            for container in spec.get("containers", [])
            if isinstance(container, dict)
        ],
        "container_statuses": [
            {
                "name": str(container.get("name", "")),
                "ready": bool(container.get("ready")),
                "restart_count": int(container.get("restartCount", 0) or 0),
                "state": container.get("state") or {},
                "last_state": container.get("lastState") or {},
            }
            for container in status.get("containerStatuses", [])
            if isinstance(container, dict)
        ],
    }


def _compact_event(event: dict[str, Any]) -> dict[str, Any]:
    """Keep the diagnostic signal while bounding the LLM prompt."""
    involved = event.get("involvedObject") or {}
    return {
        "type": str(event.get("type", "")),
        "reason": str(event.get("reason", "")),
        "message": str(event.get("message", ""))[:2000],
        "count": int(event.get("count", 0) or 0),
        "involved_object": {
            "kind": str(involved.get("kind", "")),
            "name": str(involved.get("name", "")),
        },
        "first_timestamp": event.get("firstTimestamp"),
        "last_timestamp": event.get("lastTimestamp"),
    }


def _event_matches_workload(
    event: dict[str, Any],
    workload: str,
    pod_names: set[str],
) -> bool:
    involved = event.get("involvedObject") or {}
    name = str(involved.get("name", ""))
    return (
        name == workload
        or name.startswith(f"{workload}-")
        or name in pod_names
    )


async def _collect_workload_observations(
    body: InvestigateWorkloadInput,
    pods: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[EvidenceRef]]:
    """Collect canonical observations and evidence identities before invoking the LLM.

    The facade, not the agent, owns evidence identity. The agent receives the
    actual pod names and read-tool output plus an ID/URI catalog, but it cannot
    mint evidence references that the facade did not collect.
    """
    encoded_cluster = quote(body.cluster, safe="")
    encoded_namespace = quote(body.namespace, safe="")
    encoded_workload = quote(body.workload, safe="")
    base_uri = (
        f"k8s://{encoded_cluster}/namespaces/{encoded_namespace}"
    )
    now = _now()
    observations: dict[str, Any] = {
        "pods": [_pod_observation(pod) for pod in pods],
        "events": [],
        "pod_logs": {},
        "pod_describe": {},
    }
    evidence = [EvidenceRef(
        type="workload-pod-inventory",
        source="k8s_get_resources",
        status=EvidenceStatus.available,
        reason=f"matched_pods={len(pods)}",
        uri=f"{base_uri}/pods?workload={encoded_workload}",
        collected_at=now,
    )]

    pod_names = {
        str((pod.get("metadata") or {}).get("name", ""))
        for pod in pods
    }
    pod_names.discard("")

    for observation in observations["pods"]:
        pod_name = observation["name"]
        encoded_pod = quote(pod_name, safe="")
        evidence.append(EvidenceRef(
            type="pod-status",
            source="k8s_get_resources",
            status=EvidenceStatus.available,
            reason=(
                f"phase={observation['phase']}; "
                f"containers={len(observation['container_statuses'])}"
            ),
            uri=f"{base_uri}/pods/{encoded_pod}/status",
            collected_at=now,
        ))

    try:
        event_data = await _call_read_tool(
            "k8s_get_events", {"namespace": body.namespace}
        )
        event_items = (
            event_data.get("items", [])
            if isinstance(event_data, dict)
            else []
        )
        matched_events = [
            event for event in event_items
            if isinstance(event, dict)
            and _event_matches_workload(event, body.workload, pod_names)
        ][-50:]
        observations["events"] = [
            _compact_event(event) for event in matched_events
        ]
        evidence.append(EvidenceRef(
            type="events",
            source="k8s_get_events",
            status=EvidenceStatus.available,
            reason=f"matched_events={len(matched_events)}",
            uri=f"{base_uri}/workloads/{encoded_workload}/events",
            collected_at=now,
        ))
    except AgentError as exc:
        evidence.append(EvidenceRef(
            type="events",
            source="k8s_get_events",
            status=EvidenceStatus.unavailable,
            reason=str(exc),
            collected_at=now,
        ))

    for pod in pods:
        metadata = pod.get("metadata") or {}
        spec = pod.get("spec") or {}
        pod_name = str(metadata.get("name", ""))
        encoded_pod = quote(pod_name, safe="")
        try:
            described = await _call_read_tool("k8s_describe_resource", {
                "resource_type": "pod",
                "resource_name": pod_name,
                "namespace": body.namespace,
            })
            describe_text = (
                json.dumps(described, sort_keys=True)
                if not isinstance(described, str)
                else described
            )
            observations["pod_describe"][pod_name] = (
                f"collected ({len(describe_text)} characters); "
                "cite its catalog URI when needed"
            )
            evidence.append(EvidenceRef(
                type="describe",
                source="k8s_describe_resource",
                status=EvidenceStatus.available,
                reason="pod describe collected",
                uri=f"{base_uri}/pods/{encoded_pod}/describe",
                collected_at=now,
            ))
        except AgentError as exc:
            evidence.append(EvidenceRef(
                type="describe",
                source="k8s_describe_resource",
                status=EvidenceStatus.unavailable,
                reason=str(exc),
                collected_at=now,
            ))

        for container in spec.get("containers", []):
            if not isinstance(container, dict) or not container.get("name"):
                continue
            container_name = str(container["name"])
            log_key = f"{pod_name}/{container_name}"
            log_uri = (
                f"{base_uri}/pods/{encoded_pod}/logs"
                f"?container={quote(container_name, safe='')}"
            )
            try:
                logs = await _call_read_tool("k8s_get_pod_logs", {
                    "pod_name": pod_name,
                    "namespace": body.namespace,
                    "container": container_name,
                    "tail_lines": 50,
                })
                log_text = (
                    json.dumps(logs, sort_keys=True)
                    if not isinstance(logs, str)
                    else logs
                )
                observations["pod_logs"][log_key] = log_text[:8000]
                evidence.append(EvidenceRef(
                    type="pod_logs",
                    source="k8s_get_pod_logs",
                    status=EvidenceStatus.available,
                    reason="last 50 lines collected",
                    uri=log_uri,
                    collected_at=now,
                ))
            except AgentError as exc:
                evidence.append(EvidenceRef(
                    type="pod_logs",
                    source="k8s_get_pod_logs",
                    status=EvidenceStatus.unavailable,
                    reason=str(exc),
                    collected_at=now,
                ))

    observations["evidence_catalog"] = [
        {
            "id": item.id,
            "type": item.type,
            "source": item.source,
            "status": item.status.value,
            "reason": item.reason,
            "uri": item.uri,
        }
        for item in evidence
        if item.status == EvidenceStatus.available
    ]
    observations["allowed_evidence_ids"] = [
        item["id"] for item in observations["evidence_catalog"]
    ]
    return observations, evidence


def _pod_inventory_report(
    body: InvestigateWorkloadInput,
    pods: list[dict[str, Any]],
    context: dict[str, Any],
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
            **context,
            summary=summary,
            symptoms=[f"No pods currently match workload {body.workload}."],
            evidence=evidence,
        )
    if all_running and ready_count == len(pods) and restart_count == 0:
        return WorkloadInvestigation(
            **context,
            summary=summary + " No current pod readiness or restart symptom was observed.",
            evidence=evidence,
        )
    return None


def _extract_json(text: str) -> Optional[dict]:
    """Pull a JSON object out of an LLM reply (tolerates ```json fences / prose)."""
    candidates: list[str] = []
    fenced = re.search(
        r"```(?:json)?\s*(\{.*\})\s*```",
        text,
        re.DOTALL,
    )
    if fenced:
        candidates.append(fenced.group(1))
    i, j = text.find("{"), text.rfind("}")
    if i != -1 and j > i:
        candidates.append(text[i : j + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
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


def _grounded_hypotheses(
    evidence: list[EvidenceRef],
    hypotheses: list[RankedHypothesis],
) -> list[RankedHypothesis]:
    """Keep only causes whose supporting and contradicting refs were collected."""
    known_ids = {item.id for item in evidence}
    uri_to_id = {
        item.uri: item.id for item in evidence
        if item.status == EvidenceStatus.available and item.uri
    }
    confidence_rank = {
        Confidence.high: 3,
        Confidence.medium: 2,
        Confidence.low: 1,
    }
    grounded = []
    for hypothesis in hypotheses:
        supporting_ids = [uri_to_id.get(ref, ref) for ref in hypothesis.evidence_refs]
        contradicting_ids = [
            uri_to_id.get(ref, ref) for ref in hypothesis.contradicting_evidence_refs
        ]
        normalized = hypothesis.model_copy(
            update={
                "evidence_refs": supporting_ids,
                "contradicting_evidence_refs": contradicting_ids,
            }
        )
        if (
            supporting_ids
            and all(ref in known_ids for ref in supporting_ids)
            and all(ref in known_ids for ref in contradicting_ids)
            and normalized.counter_evidence_status != CounterEvidence.not_checked
        ):
            grounded.append(normalized)
    return sorted(
        grounded,
        key=lambda hypothesis: confidence_rank[hypothesis.confidence],
        reverse=True,
    )


def _investigation_validation_errors(
    symptoms: list[str],
    evidence: list[EvidenceRef],
    hypotheses: list[RankedHypothesis],
    reported_evidence: Optional[list[EvidenceRef]] = None,
) -> list[str]:
    """Reject LLM claims that are not linked to retrievable evidence.

    The facade is the trust boundary: schema-valid JSON from an agent is not
    automatically factual. Available evidence must have a URI, while every
    hypothesis reference must resolve to a stable ID. This intentionally permits
    a hypothesis to reference unavailable evidence whose absence affected the
    assessment. ADR-021 also forbids finalized hypotheses whose counter-evidence
    was never checked.
    """
    errors: list[str] = []
    known_ids = {item.id for item in evidence}
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

    if (symptoms or hypotheses) and not known_ids:
        errors.append("diagnostic claims have no referenced evidence")
    if not hypotheses:
        errors.append("provider returned no grounded probable causes")

    unknown_reported_uris = [
        item.uri for item in reported_evidence or []
        if item.status == EvidenceStatus.available
        and item.uri not in available_uris
    ]
    if unknown_reported_uris:
        errors.append("agent returned evidence outside the collected catalog")

    confidence_rank = {
        Confidence.high: 3,
        Confidence.medium: 2,
        Confidence.low: 1,
    }
    ranks = [
        confidence_rank[hypothesis.confidence]
        for hypothesis in hypotheses
    ]
    if ranks != sorted(ranks, reverse=True):
        errors.append("probable causes are not ranked by descending confidence")

    for index, hypothesis in enumerate(hypotheses, start=1):
        if not hypothesis.evidence_refs:
            errors.append(f"hypothesis {index} has no evidence_refs")
        unknown_refs = [
            ref for ref in hypothesis.evidence_refs
            if ref not in known_ids
        ]
        if unknown_refs:
            errors.append(
                f"hypothesis {index} references unknown evidence: "
                + ", ".join(unknown_refs)
            )
        unknown_counter_refs = [
            ref for ref in hypothesis.contradicting_evidence_refs
            if ref not in known_ids
        ]
        if unknown_counter_refs:
            errors.append(
                f"hypothesis {index} references unknown counter-evidence"
            )
        if hypothesis.counter_evidence_status == CounterEvidence.not_checked:
            errors.append(f"hypothesis {index} did not check counter-evidence")

    return errors


# ── prompt builders (ask the agent for STRICT JSON in the contract shape) ────
def _instruct(
    function: str,
    payload: dict,
    shape: str,
    observations: Optional[dict[str, Any]] = None,
) -> str:
    grounding = (
        "\nFACADE-COLLECTED OBSERVATIONS (authoritative):\n"
        f"{json.dumps(observations, default=str)}\n"
        if observations is not None
        else ""
    )
    return (
        f"FUNCTION: {function}\n"
        f"INPUT: {json.dumps(payload)}\n"
        f"{grounding}\n"
        "You are read-only. Perform the diagnosis using your read tools, then respond\n"
        "with ONLY a single JSON object (no prose, no markdown fences) of EXACTLY this shape:\n"
        f"{shape}\n"
        "Rules:\n"
        "- Do NOT ask clarifying questions or request more input. Assess with the tools\n"
        "  available and return the JSON regardless of what is missing.\n"
        "- Every evidence_refs and contradicting_evidence_refs item MUST be an exact\n"
        "  copy of an id from the evidence array; never reference URI/type/source labels.\n"
        "- When facade-collected observations are present, they are authoritative.\n"
        "  Do not call tools again. Copy evidence entries only from evidence_catalog,\n"
        "  and copy hypothesis references only from allowed_evidence_ids. Never invent\n"
        "  a resource name, pod name, event, log observation, or URI. Rank causes by\n"
        "  descending confidence and make the first cause the best explanation of\n"
        "  the observed states, events, and logs. If a container started and exited,\n"
        "  do not diagnose an image-pull failure.\n"
        "- Never paste raw logs or secrets into evidence.\n"
        "- Every probable cause needs counter_evidence_status found|none_found.\n"
        "  not_checked makes the finalized result unverified and will be rejected.\n"
        "- recommended_next_steps are actions for a human.\n"
        "- Events and pod logs ARE available via your read-only tools (k8s_get_events,\n"
        "  k8s_get_pod_logs) — use them. Only host journal and node shell are unsupported;\n"
        "  mark ONLY those as unavailable evidence."
    )


_SHAPE_INVESTIGATE = (
    '{"summary":str,"symptoms":[str],'
    '"evidence":[{"id":str,"type":str,"source":str,"status":"available|unavailable|partial",'
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
    '{"evidence":[{"id":str,"type":str,"source":str,"status":"available|unavailable|partial",'
    '"reason":str,"uri":str}]}'
)


# ── the three contract functions ─────────────────────────────────────────────
@app.post(
    "/v1/get_platform_health",
    response_model=PlatformHealth,
    response_model_exclude_none=True,
    operation_id="get_platform_health",
    dependencies=[Depends(require_consumer_identity)],
)
async def get_platform_health(
    body: GetPlatformHealthInput,
    request: Request,
) -> PlatformHealth:
    clusters = body.clusters or [DEFAULT_CLUSTER]
    try:
        text = await invoke_agent(_instruct("get_platform_health", body.model_dump(), _SHAPE_HEALTH))
    except AgentError as e:
        return PlatformHealth(
            invocation_id=request.state.invocation_id,
            generated_at=_now(),
            clusters=[
            ClusterHealth(
                cluster=c,
                status=ClusterStatus.unknown,
                summary=f"provider unavailable: {e}",
                signals=["provider_call_failed"],
            ) for c in clusters],
        )
    data = _extract_json(text) or {}
    reported: dict[str, ClusterHealth] = {}
    for c in data.get("clusters", []) if isinstance(data, dict) else []:
        if isinstance(c, dict) and c.get("cluster"):
            cluster = str(c["cluster"])
            if cluster not in clusters or cluster in reported:
                continue
            raw_status = str(c.get("status", "")).strip().lower()
            summary = str(c.get("summary", "")).strip()
            signals = list(c.get("signals", []) or [])
            if raw_status not in {
                "healthy", "degraded", "unavailable", "unknown"
            }:
                reported_status = raw_status or "<missing>"
                raw_status = "unknown"
                summary = (
                    f"provider returned unverified platform health status "
                    f"{reported_status!r}"
                    f"{f': {summary}' if summary else ''}"
                )
                signals.append("provider_status_unverified")
            reported[cluster] = ClusterHealth(
                cluster=cluster,
                status=raw_status,
                summary=summary,
                signals=signals,
            )
    out = []
    for cluster in clusters:
        if cluster in reported:
            out.append(reported[cluster])
            continue
        reason = (
            "reply was not structured JSON"
            if not data
            else "requested cluster is missing from the structured response"
        )
        out.append(ClusterHealth(
            cluster=cluster,
            status=ClusterStatus.unknown,
            summary=f"provider returned unverified platform health output: {reason}",
            signals=["provider_output_unverified"],
        ))
    return PlatformHealth(
        invocation_id=request.state.invocation_id,
        generated_at=_now(),
        clusters=out,
    )


@app.post(
    "/v1/investigate_workload",
    response_model=WorkloadInvestigation,
    response_model_exclude_none=True,
    operation_id="investigate_workload",
    dependencies=[Depends(require_consumer_identity)],
)
async def investigate_workload(
    body: InvestigateWorkloadInput,
    request: Request,
) -> WorkloadInvestigation:
    context = _investigation_context(request, body)
    try:
        pods = await _get_workload_pods(body)
    except AgentError as e:
        LOGGER.error(
            "workload inventory failed invocation_id=%s error_type=%s",
            request.state.invocation_id,
            type(e).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail={
                "code": "provider_unavailable",
                "message": "workload inventory provider is unavailable",
            },
        )
    inventory_report = _pod_inventory_report(body, pods, context)
    if inventory_report is not None:
        return inventory_report

    observations, canonical_evidence = await _collect_workload_observations(
        body, pods
    )
    try:
        text = await invoke_agent(_instruct(
            "investigate_workload",
            body.model_dump(),
            _SHAPE_INVESTIGATE,
            observations,
        ))
    except AgentError as e:
        LOGGER.error(
            "diagnostics agent failed invocation_id=%s error_type=%s",
            request.state.invocation_id,
            type(e).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail={
                "code": "provider_unavailable",
                "message": "diagnostics agent is unavailable",
            },
        )
    data = _extract_json(text)
    if not data:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "provider_unavailable",
                "message": "diagnostics agent did not return a finalized result",
            },
        )
    symptoms = list(data.get("symptoms", []) or [])
    reported_evidence = _coerce_evidence(data.get("evidence"))
    hypotheses = _grounded_hypotheses(
        canonical_evidence,
        _coerce_hypotheses(data.get("probable_causes")),
    )
    validation_errors = _investigation_validation_errors(
        symptoms,
        canonical_evidence,
        hypotheses,
        reported_evidence,
    )
    if validation_errors:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "provider_unavailable",
                "message": "diagnostics agent returned an unverified result: "
                + "; ".join(validation_errors),
            },
        )
    return WorkloadInvestigation(
        **context,
        summary=str(data.get("summary", "")).strip() or text[:500],
        symptoms=symptoms,
        evidence=canonical_evidence,
        probable_causes=hypotheses,
        recommended_next_steps=list(data.get("recommended_next_steps", []) or []),
        references=list(data.get("references", []) or []))


@app.post(
    "/v1/collect_diagnostic_evidence",
    response_model=EvidenceBundle,
    response_model_exclude_none=True,
    operation_id="collect_diagnostic_evidence",
    dependencies=[Depends(require_consumer_identity)],
)
async def collect_diagnostic_evidence(
    body: CollectDiagnosticEvidenceInput,
    request: Request,
) -> EvidenceBundle:
    requested = set(body.evidence_types) or {"events", "logs", "describe"}
    collected_at = _now()
    context = {
        "invocation_id": request.state.invocation_id,
        "cluster": body.cluster,
        "namespace": body.namespace,
        "workload": body.workload,
        "collected_at": collected_at,
        "effective_time_range": _effective_time_range(
            body.time_range, collected_at
        ),
    }
    investigation_input = InvestigateWorkloadInput(
        cluster=body.cluster,
        namespace=body.namespace,
        workload=body.workload,
        time_range=body.time_range,
    )
    try:
        pods = await _get_workload_pods(investigation_input)
        _, canonical_evidence = await _collect_workload_observations(
            investigation_input, pods
        )
    except AgentError as e:
        return EvidenceBundle(
            **context,
            evidence=[
                EvidenceRef(
                    type=evidence_type,
                    source=PROVIDER_NAME,
                    status=EvidenceStatus.unavailable,
                    reason=str(e),
                    collected_at=_now(),
                )
                for evidence_type in sorted(requested)
            ],
        )

    type_aliases = {"pod_logs": "logs"}
    evidence: list[EvidenceRef] = []
    for item in canonical_evidence:
        evidence_type = type_aliases.get(item.type, item.type)
        if evidence_type in requested:
            evidence.append(item.model_copy(update={"type": evidence_type}))

    for evidence_type in sorted(requested):
        if any(item.type == evidence_type for item in evidence):
            continue
        capability = {
            "events": "workload_events",
            "logs": "workload_logs",
            "host_journal": "host_journal",
            "node_shell": "node_shell",
        }.get(evidence_type)
        unavailable_reason = (
            f"{evidence_type} is not supported by this provider profile"
            if capability and not PROVIDER_CAPS.get(capability, False)
            else f"no {evidence_type} evidence was collected"
        )
        evidence.append(EvidenceRef(
            type=evidence_type,
            source=PROVIDER_NAME,
            status=EvidenceStatus.unavailable,
            reason=unavailable_reason,
            collected_at=_now(),
        ))

    return EvidenceBundle(
        **context,
        evidence=evidence,
    )


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict:
    return {"status": "ok", "kagent": KAGENT_BASE_URL, "agent": KAGENT_AGENT}
