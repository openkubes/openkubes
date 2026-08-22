#!/usr/bin/env python3
"""Read-only OpenKubes observed-state producer for the Console BFF."""

from __future__ import annotations

import json
import os
import re
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote
from urllib.request import Request, urlopen

QUERY_VERSION = "observed.openkubes.io/v0alpha1"
QUERY_KIND = "ConsoleObservedState"
QUERY_PATH = "/api/console-observed-state/v0alpha1"
CLAIM_API_VERSION = "platform.openkubes.ai/v1alpha1"
CLAIM_KIND = "KubeVirtClusterClaim"
DNS_LABEL = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
MAX_TLS_FILE_BYTES = 64 * 1024


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def bounded_string(value: Any, fallback: str, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        return fallback
    return value


def safe_timestamp(value: Any, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return fallback
    return value


def ready_condition(resource: dict[str, Any]) -> tuple[str, str | None]:
    conditions = resource.get("status", {}).get("conditions", [])
    if not isinstance(conditions, list):
        return "Unknown", None
    for condition in conditions:
        if not isinstance(condition, dict) or condition.get("type") != "Ready":
            continue
        status = condition.get("status")
        observed_at = condition.get("lastTransitionTime")
        if status == "True":
            return "Ready", observed_at if isinstance(observed_at, str) else None
        if status == "False":
            return "Pending", observed_at if isinstance(observed_at, str) else None
        return "Unknown", observed_at if isinstance(observed_at, str) else None
    return "Unknown", None


@dataclass(frozen=True)
class ProducerConfig:
    namespace: str = "openkubes-system"
    environment_id: str = "openkubes-management"
    environment_name: str = "OpenKubes management plane"
    management_name: str = "ok-mgmt"
    management_provider: str = "OpenKubes"
    management_profile: str = "Management plane"
    management_region: str = "unknown"
    management_kubernetes_version: str = "unknown"

    @classmethod
    def from_environment(cls, environment: dict[str, str] | os._Environ[str] = os.environ) -> "ProducerConfig":
        namespace = environment.get("OK_OBSERVER_NAMESPACE", "openkubes-system")
        management_name = environment.get("OK_OBSERVER_MANAGEMENT_NAME", "ok-mgmt")
        for name, value in (("OK_OBSERVER_NAMESPACE", namespace), ("OK_OBSERVER_MANAGEMENT_NAME", management_name)):
            if not DNS_LABEL.fullmatch(value):
                raise ValueError(f"{name} must be a DNS label.")
        return cls(
            namespace=namespace,
            environment_id=bounded_string(environment.get("OK_OBSERVER_ENVIRONMENT_ID"), "openkubes-management"),
            environment_name=bounded_string(environment.get("OK_OBSERVER_ENVIRONMENT_NAME"), "OpenKubes management plane"),
            management_name=management_name,
            management_provider=bounded_string(environment.get("OK_OBSERVER_MANAGEMENT_PROVIDER"), "OpenKubes"),
            management_profile=bounded_string(environment.get("OK_OBSERVER_MANAGEMENT_PROFILE"), "Management plane"),
            management_region=bounded_string(environment.get("OK_OBSERVER_MANAGEMENT_REGION"), "unknown"),
            management_kubernetes_version=bounded_string(environment.get("OK_OBSERVER_MANAGEMENT_KUBERNETES_VERSION"), "unknown"),
        )


@dataclass(frozen=True)
class TlsConfig:
    certificate_file: Path
    private_key_file: Path
    client_ca_file: Path
    expected_client_identity: str

    @classmethod
    def from_environment(cls, environment: dict[str, str] | os._Environ[str] = os.environ) -> "TlsConfig":
        values = {
            "OK_OBSERVER_TLS_CERT_FILE": environment.get("OK_OBSERVER_TLS_CERT_FILE", ""),
            "OK_OBSERVER_TLS_KEY_FILE": environment.get("OK_OBSERVER_TLS_KEY_FILE", ""),
            "OK_OBSERVER_TLS_CLIENT_CA_FILE": environment.get("OK_OBSERVER_TLS_CLIENT_CA_FILE", ""),
            "OK_OBSERVER_TLS_CLIENT_IDENTITY": environment.get("OK_OBSERVER_TLS_CLIENT_IDENTITY", ""),
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ValueError(f"Missing required TLS file configuration: {', '.join(missing)}")
        identity = values.pop("OK_OBSERVER_TLS_CLIENT_IDENTITY")
        if not identity.startswith("spiffe://") or len(identity) > 512:
            raise ValueError("OK_OBSERVER_TLS_CLIENT_IDENTITY must be a bounded SPIFFE URI.")
        paths = {name: Path(value) for name, value in values.items()}
        for name, path in paths.items():
            if not path.is_file():
                raise ValueError(f"{name} must reference a mounted regular file.")
            size = path.stat().st_size
            if size < 1 or size > MAX_TLS_FILE_BYTES:
                raise ValueError(f"{name} must contain between 1 and {MAX_TLS_FILE_BYTES} bytes.")
        return cls(
            certificate_file=paths["OK_OBSERVER_TLS_CERT_FILE"],
            private_key_file=paths["OK_OBSERVER_TLS_KEY_FILE"],
            client_ca_file=paths["OK_OBSERVER_TLS_CLIENT_CA_FILE"],
            expected_client_identity=identity,
        )


def server_tls_context(config: TlsConfig) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=config.certificate_file, keyfile=config.private_key_file)
    context.load_verify_locations(cafile=config.client_ca_file)
    # Health probes carry no identity. Query authorization is enforced in the
    # handler; any client certificate that is presented must chain to this CA.
    context.verify_mode = ssl.CERT_OPTIONAL
    return context


class KubernetesApiClient:
    """Minimal in-cluster, read-only client. The ServiceAccount token never leaves this class."""

    def __init__(
        self,
        host: str,
        port: int,
        token_file: str = "/var/run/secrets/kubernetes.io/serviceaccount/token",
        ca_file: str = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
        timeout_seconds: float = 5.0,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        if not host or not 1 <= port <= 65535:
            raise ValueError("A valid Kubernetes API host and port are required.")
        self.base_url = f"https://{host}:{port}"
        self.token_file = Path(token_file)
        self.context = ssl.create_default_context(cafile=ca_file)
        self.timeout_seconds = timeout_seconds
        self.opener = opener

    @classmethod
    def from_environment(cls, environment: dict[str, str] | os._Environ[str] = os.environ) -> "KubernetesApiClient":
        host = environment.get("KUBERNETES_SERVICE_HOST", "")
        try:
            port = int(environment.get("KUBERNETES_SERVICE_PORT_HTTPS", "443"))
            timeout = float(environment.get("OK_OBSERVER_API_TIMEOUT_SECONDS", "5"))
        except ValueError as error:
            raise ValueError("Kubernetes port and observer timeout must be numeric.") from error
        if timeout <= 0:
            raise ValueError("OK_OBSERVER_API_TIMEOUT_SECONDS must be positive.")
        return cls(host=host, port=port, timeout_seconds=timeout)

    def list_cluster_claims(self, namespace: str) -> dict[str, Any]:
        token = self.token_file.read_text(encoding="utf-8").strip()
        if not token:
            raise RuntimeError("The mounted ServiceAccount token is empty.")
        path = f"/apis/platform.openkubes.ai/v1alpha1/namespaces/{quote(namespace, safe='')}/kubevirtclusterclaims?limit=500"
        request = Request(
            f"{self.base_url}{path}",
            method="GET",
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        )
        with self.opener(request, context=self.context, timeout=self.timeout_seconds) as response:
            if response.status != 200:
                raise RuntimeError("The Kubernetes API rejected the read-only observed-state query.")
            body = response.read(2 * 1024 * 1024 + 1)
            if len(body) > 2 * 1024 * 1024:
                raise RuntimeError("The Kubernetes API claim list exceeds the response limit.")
            payload = json.loads(body)
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise RuntimeError("The Kubernetes API returned an incompatible claim list.")
        return payload


def claim_projection(resource: dict[str, Any], observed_at: str) -> tuple[dict[str, Any], dict[str, Any]]:
    metadata = resource.get("metadata", {})
    spec = resource.get("spec", {})
    name = bounded_string(metadata.get("name"), "unknown")
    if not DNS_LABEL.fullmatch(name):
        raise ValueError("A cluster claim has an invalid metadata.name.")
    resource_version = bounded_string(metadata.get("resourceVersion"), "unknown")
    readiness, transition_time = ready_condition(resource)
    evidence_id = f"ev-{name}-claim-readiness"
    version = bounded_string(spec.get("controlPlane", {}).get("kubernetesVersion"), "unknown")
    provider = bounded_string(spec.get("provider"), "unknown")
    region = bounded_string(spec.get("country"), "unknown")
    state_detail = {
        "Ready": "The OpenKubes cluster Claim reports Ready=True.",
        "Pending": "The OpenKubes cluster Claim reports Ready=False.",
        "Unknown": "The OpenKubes cluster Claim has no recognized Ready Condition.",
    }[readiness]
    cluster = {
        "id": f"cluster-{name}",
        "name": name,
        "role": "Workload cluster",
        "provider": provider,
        "profile": "KubeVirt cluster claim",
        "kubernetesVersion": version,
        "region": region,
        "readiness": readiness,
        "compatibility": "Supported",
        "contractVersion": CLAIM_API_VERSION,
        "revision": f"resourceVersion:{resource_version}",
        "evidenceId": evidence_id,
        "capabilities": [],
        "lifecycle": [
            {"label": "Declared", "state": "Ready", "detail": "The namespaced OpenKubes cluster Claim exists."},
            {"label": "Infrastructure", "state": readiness, "detail": state_detail},
            {"label": "Control plane", "state": "Unknown", "detail": "This source exposes no normative control-plane Condition."},
            {"label": "Capabilities", "state": "Unknown", "detail": "Capability observations are not available from this source."},
        ],
    }
    evidence = {
        "id": evidence_id,
        "title": f"{name} cluster Claim readiness",
        "type": "Observation",
        "outcome": readiness,
        "clusterId": f"cluster-{name}",
        "contract": f"{CLAIM_KIND}/{CLAIM_API_VERSION.split('/')[-1]}",
        "revision": f"resourceVersion:{resource_version}",
        "observedAt": safe_timestamp(transition_time, observed_at),
        "source": "OpenKubes management-plane Kubernetes API",
        "summary": state_detail,
        "classification": "Current",
    }
    return cluster, evidence


def build_observed_state(claim_list: dict[str, Any], config: ProducerConfig, now: Callable[[], datetime] = utc_now) -> dict[str, Any]:
    observed_at = isoformat(now())
    list_metadata = claim_list.get("metadata", {})
    source_revision = bounded_string(list_metadata.get("resourceVersion"), "unknown")
    items = claim_list.get("items")
    if not isinstance(items, list):
        raise ValueError("Claim list items must be an array.")

    workload_clusters: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Every cluster Claim must be an object.")
        cluster, evidence_item = claim_projection(item, observed_at)
        workload_clusters.append(cluster)
        evidence.append(evidence_item)
    names = [cluster["name"] for cluster in workload_clusters]
    if config.management_name in names or len(names) != len(set(names)):
        raise ValueError("Observed cluster identities must be unique and distinct from the management plane.")
    workload_clusters.sort(key=lambda cluster: cluster["name"])

    management_evidence_id = "ev-ok-mgmt-source-boundary"
    management_cluster = {
        "id": f"cluster-{config.management_name}",
        "name": config.management_name,
        "role": "Management plane",
        "provider": config.management_provider,
        "profile": config.management_profile,
        "kubernetesVersion": config.management_kubernetes_version,
        "region": config.management_region,
        "readiness": "Unknown",
        "compatibility": "Read only",
        "contractVersion": "unknown",
        "revision": f"claimListResourceVersion:{source_revision}",
        "evidenceId": management_evidence_id,
        "capabilities": [],
        "lifecycle": [
            {"label": "Declared", "state": "Unknown", "detail": "No normative Management Plane Contract is available from this source."},
            {"label": "Infrastructure", "state": "Unknown", "detail": "Infrastructure readiness is outside this source boundary."},
            {"label": "Control plane", "state": "Unknown", "detail": "API reachability is not converted into normative readiness."},
            {"label": "Capabilities", "state": "Unknown", "detail": "Capability observations are not available from this source."},
        ],
    }
    evidence.insert(0, {
        "id": management_evidence_id,
        "title": "Management plane observation boundary",
        "type": "Observation",
        "outcome": "Unknown",
        "clusterId": f"cluster-{config.management_name}",
        "contract": "Unavailable",
        "revision": f"claimListResourceVersion:{source_revision}",
        "observedAt": observed_at,
        "source": "OpenKubes observed-state producer",
        "summary": "Management plane identity is configured, but this source has no normative readiness Contract.",
        "classification": "Current",
    })

    return {
        "apiVersion": QUERY_VERSION,
        "kind": QUERY_KIND,
        "metadata": {
            "observedAt": observed_at,
            "sourceRevision": f"kubevirtclusterclaims:{source_revision}",
            "partial": True,
        },
        "data": {
            "environment": {"id": config.environment_id, "displayName": config.environment_name},
            "metrics": {
                "capabilities": {"total": 0, "ready": 0, "pending": 0, "failed": 0, "unknown": 0},
                "workloadClaims": {"total": 0, "ready": 0, "pending": 0, "failed": 0, "unknown": 0},
                "openFindings": {"total": 0, "critical": 0},
            },
            "clusters": [management_cluster, *workload_clusters],
            "placements": [],
            "evidence": evidence,
        },
    }


class ObservedStateProducer:
    def __init__(self, client: KubernetesApiClient, config: ProducerConfig, now: Callable[[], datetime] = utc_now) -> None:
        self.client = client
        self.config = config
        self.now = now

    def snapshot(self) -> dict[str, Any]:
        return build_observed_state(self.client.list_cluster_claims(self.config.namespace), self.config, self.now)


def handler_for(
    producer: ObservedStateProducer,
    require_client_identity: bool = True,
    expected_client_identity: str | None = None,
) -> type[BaseHTTPRequestHandler]:
    if require_client_identity and not expected_client_identity:
        raise ValueError("An expected client workload identity is required.")

    class Handler(BaseHTTPRequestHandler):
        def send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", f'application/json; profile="{QUERY_VERSION}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/healthz":
                self.send_json(200, {"status": "ok"})
                return
            if self.path != QUERY_PATH:
                self.send_json(404, {"error": "not_found"})
                return
            peer_certificate = getattr(self.connection, "getpeercert", lambda: None)() or {}
            peer_identities = {
                value for kind, value in peer_certificate.get("subjectAltName", ()) if kind == "URI"
            }
            if require_client_identity and expected_client_identity not in peer_identities:
                self.send_json(403, {"error": "workload_identity_required"})
                return
            try:
                self.send_json(200, producer.snapshot())
            except Exception:
                self.send_json(503, {"error": "source_unavailable", "retryable": True})

        def do_POST(self) -> None:  # noqa: N802
            self.send_json(405, {"error": "method_not_allowed"})

        def log_message(self, format: str, *args: Any) -> None:
            print(f"observed-state-producer {self.command} {self.path} {args[1] if len(args) > 1 else '-'}")

    return Handler


def main() -> None:
    config = ProducerConfig.from_environment()
    tls = TlsConfig.from_environment()
    client = KubernetesApiClient.from_environment()
    host = os.environ.get("OK_OBSERVER_HOST", "0.0.0.0")
    port = int(os.environ.get("OK_OBSERVER_PORT", "8443"))
    server = ThreadingHTTPServer(
        (host, port),
        handler_for(ObservedStateProducer(client, config), expected_client_identity=tls.expected_client_identity),
    )
    server.socket = server_tls_context(tls).wrap_socket(server.socket, server_side=True)
    print(f"OpenKubes observed-state producer listening with authenticated TLS on {host}:{port}{QUERY_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    main()
