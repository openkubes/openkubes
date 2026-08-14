"""Deterministic non-LLM provider for the ADR-021 diagnostics contract.

Profile B exists to prove that consumers and the contract suite are not coupled
to an agent runtime. It has no Kubernetes client, kubeconfig, credentials, or
provider-specific dependencies. Responses are synthetic and deterministic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import quote, urlsplit


CAPABILITIES = {
    "workload_events": True,
    "workload_logs": True,
    "cilium_diagnostics": False,
    "host_journal": False,
    "node_shell": False,
}
SUPPORTED_EVIDENCE = {"events", "logs", "describe"}
DEFAULT_EVIDENCE = ["events", "logs", "describe"]
MAX_REQUEST_BYTES = 1_048_576
_INVOCATION_LOCK = threading.Lock()
_INVOCATION_SEQUENCE = 0


class RequestError(ValueError):
    """The consumer request is not valid for the selected operation."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _next_invocation_id() -> str:
    global _INVOCATION_SEQUENCE
    with _INVOCATION_LOCK:
        _INVOCATION_SEQUENCE += 1
        return f"inv-profile-b-{_INVOCATION_SEQUENCE:08d}"


def _effective_time_range(end: str) -> dict[str, str]:
    end_time = datetime.fromisoformat(end.replace("Z", "+00:00"))
    start_time = end_time - timedelta(hours=1)
    return {
        "start": start_time.isoformat().replace("+00:00", "Z"),
        "end": end,
    }


def _validate_object(
    payload: Any,
    *,
    required: set[str],
    allowed: set[str],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RequestError("request body must be a JSON object")
    missing = sorted(required - payload.keys())
    if missing:
        raise RequestError("missing required field(s): " + ", ".join(missing))
    unknown = sorted(payload.keys() - allowed)
    if unknown:
        raise RequestError("unknown field(s): " + ", ".join(unknown))
    for field in required:
        if not isinstance(payload[field], str) or not payload[field].strip():
            raise RequestError(f"{field} must be a non-empty string")
    if "time_range" in payload and (
        not isinstance(payload["time_range"], str) or not payload["time_range"].strip()
    ):
        raise RequestError("time_range must be a non-empty ISO-8601 duration")
    return payload


def _evidence_uri(payload: dict[str, Any], evidence_type: str) -> str:
    parts = [
        quote(str(payload[field]), safe="")
        for field in ("cluster", "namespace", "workload")
    ]
    return "evidence://profile-b/" + "/".join(parts + [quote(evidence_type, safe="")])


def _evidence_ref(
    payload: dict[str, Any],
    evidence_type: str,
    collected_at: str,
    invocation_id: str,
    index: int,
) -> dict[str, Any]:
    type_digest = hashlib.sha256(evidence_type.encode("utf-8")).hexdigest()[:12]
    evidence_id = f"{invocation_id}-ev-{index:03d}-{type_digest}"
    if evidence_type in SUPPORTED_EVIDENCE:
        return {
            "id": evidence_id,
            "type": evidence_type,
            "source": "profile-b-runbook",
            "status": "available",
            "uri": _evidence_uri(payload, evidence_type),
            "collected_at": collected_at,
        }
    return {
        "id": evidence_id,
        "type": evidence_type,
        "source": "profile-b-runbook",
        "status": "unavailable",
        "reason": f"{evidence_type} is not supported by Profile B",
        "collected_at": collected_at,
    }


def get_platform_health(payload: Any, invocation_id: str) -> dict[str, Any]:
    body = _validate_object(payload, required=set(), allowed={"clusters"})
    clusters = body.get("clusters") or ["stub-cluster"]
    if not isinstance(clusters, list) or any(
        not isinstance(cluster, str) or not cluster.strip() for cluster in clusters
    ):
        raise RequestError("clusters must be an array of non-empty strings")
    generated_at = _now()
    return {
        "invocation_id": invocation_id,
        "generated_at": generated_at,
        "clusters": [
            {
                "cluster": cluster,
                "status": "healthy",
                "summary": "Profile B deterministic health fixture is available.",
                "signals": [],
                "provider_capabilities": dict(CAPABILITIES),
            }
            for cluster in clusters
        ],
    }


def investigate_workload(payload: Any, invocation_id: str) -> dict[str, Any]:
    body = _validate_object(
        payload,
        required={"cluster", "namespace", "workload"},
        allowed={"cluster", "namespace", "workload", "time_range"},
    )
    collected_at = _now()
    evidence = [
        _evidence_ref(body, "events", collected_at, invocation_id, 1),
        _evidence_ref(body, "logs", collected_at, invocation_id, 2),
    ]
    supporting_id = evidence[0]["id"]
    return {
        "invocation_id": invocation_id,
        "cluster": body["cluster"],
        "namespace": body["namespace"],
        "workload": body["workload"],
        "generated_at": collected_at,
        "effective_time_range": _effective_time_range(collected_at),
        "summary": (
            f"Deterministic fixture diagnosis for {body['namespace']}/"
            f"{body['workload']} on {body['cluster']}."
        ),
        "symptoms": ["fixture reports one unavailable application dependency"],
        "evidence": evidence,
        "probable_causes": [
            {
                "hypothesis": "The fixture dependency is unavailable.",
                "confidence": "high",
                "evidence_refs": [supporting_id],
                "contradicting_evidence_refs": [],
                "counter_evidence_status": "none_found",
            }
        ],
        "recommended_next_steps": [
            "Have an operator inspect the referenced event and dependency state."
        ],
        "references": ["runbook://profile-b/dependency-unavailable"],
        "provider_capabilities": dict(CAPABILITIES),
    }


def collect_diagnostic_evidence(payload: Any, invocation_id: str) -> dict[str, Any]:
    body = _validate_object(
        payload,
        required={"cluster", "namespace", "workload"},
        allowed={
            "cluster",
            "namespace",
            "workload",
            "time_range",
            "evidence_types",
        },
    )
    evidence_types = body.get("evidence_types") or DEFAULT_EVIDENCE
    if not isinstance(evidence_types, list) or any(
        not isinstance(item, str) or not item.strip() for item in evidence_types
    ):
        raise RequestError("evidence_types must be an array of non-empty strings")
    collected_at = _now()
    return {
        "invocation_id": invocation_id,
        "cluster": body["cluster"],
        "namespace": body["namespace"],
        "workload": body["workload"],
        "collected_at": collected_at,
        "effective_time_range": _effective_time_range(collected_at),
        "evidence": [
            _evidence_ref(body, evidence_type, collected_at, invocation_id, index)
            for index, evidence_type in enumerate(dict.fromkeys(evidence_types), 1)
        ],
        "provider_capabilities": dict(CAPABILITIES),
    }


OPERATIONS = {
    "/v1/get_platform_health": get_platform_health,
    "/v1/investigate_workload": investigate_workload,
    "/v1/collect_diagnostic_evidence": collect_diagnostic_evidence,
}


class ProfileBHandler(BaseHTTPRequestHandler):
    """Small HTTP transport wrapper around the deterministic operations."""

    server_version = "OpenKubesProfileB/1.1"

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        invocation_id = _next_invocation_id()
        operation = OPERATIONS.get(urlsplit(self.path).path)
        if operation is None:
            self._write_json(
                404,
                {
                    "code": "not_found",
                    "message": "unknown operation",
                    "invocation_id": invocation_id,
                },
                invocation_id,
            )
            return
        authorization = self.headers.get("Authorization", "")
        if not authorization.startswith("Bearer ") or not authorization[7:].strip():
            self._write_json(
                401,
                {
                    "code": "unauthorized",
                    "message": "a consumer bearer identity is required",
                    "invocation_id": invocation_id,
                },
                invocation_id,
            )
            return
        try:
            request_id = self.headers.get("X-Request-Id")
            if request_id is not None and (not request_id or len(request_id) > 128):
                raise RequestError("X-Request-Id must contain 1 to 128 characters")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise RequestError("Content-Length must be an integer") from exc
            if length < 0:
                raise RequestError("Content-Length must not be negative")
            if length > MAX_REQUEST_BYTES:
                raise RequestError("request body exceeds 1 MiB")
            payload = json.loads(self.rfile.read(length) or b"{}")
            result = operation(payload, invocation_id)
        except (json.JSONDecodeError, RequestError) as exc:
            self._write_json(
                400,
                {
                    "code": "invalid_request",
                    "message": str(exc),
                    "invocation_id": invocation_id,
                },
                invocation_id,
            )
            return
        self._write_json(200, result, invocation_id)

    def _write_json(
        self,
        status: int,
        payload: dict[str, Any],
        invocation_id: str,
    ) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Invocation-Id", invocation_id)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), ProfileBHandler)
    print(f"Profile B listening on http://{args.host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
