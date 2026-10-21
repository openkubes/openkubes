#!/usr/bin/env python3
"""Read-only OpenKubes observed-state producer for the Console BFF."""

from __future__ import annotations

import copy
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
QUERY_V2_VERSION = "observed.openkubes.io/v0alpha2"
QUERY_V2_PATH = "/api/console-observed-state/v0alpha2"
MAX_OWNERSHIP_FILE_BYTES = 64 * 1024
CLAIM_API_VERSION = "platform.openkubes.ai/v1alpha1"
CLAIM_KIND = "KubeVirtClusterClaim"
AGENT_CONTRACT_VERSION = "agents.openkubes.io/v1alpha1"
AGENT_DEPLOYMENT_KIND = "AgentDeployment"
AGENT_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
DNS_LABEL = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
MAX_TLS_FILE_BYTES = 64 * 1024
MAX_CLUSTER_OBSERVATIONS_BYTES = 128 * 1024


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
    source_mode: str = "kubevirt-claims"
    namespace: str = "openkubes-system"
    environment_id: str = "openkubes-management"
    environment_name: str = "OpenKubes management plane"
    management_name: str = "ok-mgmt"
    management_provider: str = "OpenKubes"
    management_profile: str = "Management plane"
    management_region: str = "unknown"
    management_kubernetes_version: str = "unknown"
    hosting_name: str = "ok-shared"
    hosting_namespace: str = "openkubes-console"
    hosting_deployment: str = "ok-console"
    hosting_region: str = "unknown"
    ownership_file: str = ""
    cluster_observations_file: str = ""

    @classmethod
    def from_environment(cls, environment: dict[str, str] | os._Environ[str] = os.environ) -> "ProducerConfig":
        source_mode = environment.get("OK_OBSERVER_SOURCE_MODE", "kubevirt-claims")
        if source_mode not in {"kubevirt-claims", "hosting-cluster"}:
            raise ValueError("OK_OBSERVER_SOURCE_MODE must be kubevirt-claims or hosting-cluster.")
        namespace = environment.get("OK_OBSERVER_NAMESPACE", "openkubes-system")
        management_name = environment.get("OK_OBSERVER_MANAGEMENT_NAME", "ok-mgmt")
        hosting_name = environment.get("OK_OBSERVER_HOSTING_NAME", "ok-shared")
        hosting_namespace = environment.get("OK_OBSERVER_HOSTING_NAMESPACE", "openkubes-console")
        hosting_deployment = environment.get("OK_OBSERVER_HOSTING_DEPLOYMENT", "ok-console")
        for name, value in (
            ("OK_OBSERVER_NAMESPACE", namespace),
            ("OK_OBSERVER_MANAGEMENT_NAME", management_name),
            ("OK_OBSERVER_HOSTING_NAME", hosting_name),
            ("OK_OBSERVER_HOSTING_NAMESPACE", hosting_namespace),
            ("OK_OBSERVER_HOSTING_DEPLOYMENT", hosting_deployment),
        ):
            if not DNS_LABEL.fullmatch(value):
                raise ValueError(f"{name} must be a DNS label.")
        if hosting_name == management_name:
            raise ValueError("The hosting cluster must be distinct from the management plane.")
        return cls(
            source_mode=source_mode,
            ownership_file=environment.get("OK_OBSERVER_OWNERSHIP_FILE", ""),
            cluster_observations_file=environment.get("OK_OBSERVER_CLUSTER_OBSERVATIONS_FILE", ""),
            namespace=namespace,
            environment_id=bounded_string(environment.get("OK_OBSERVER_ENVIRONMENT_ID"), "openkubes-management"),
            environment_name=bounded_string(environment.get("OK_OBSERVER_ENVIRONMENT_NAME"), "OpenKubes management plane"),
            management_name=management_name,
            management_provider=bounded_string(environment.get("OK_OBSERVER_MANAGEMENT_PROVIDER"), "OpenKubes"),
            management_profile=bounded_string(environment.get("OK_OBSERVER_MANAGEMENT_PROFILE"), "Management plane"),
            management_region=bounded_string(environment.get("OK_OBSERVER_MANAGEMENT_REGION"), "unknown"),
            management_kubernetes_version=bounded_string(environment.get("OK_OBSERVER_MANAGEMENT_KUBERNETES_VERSION"), "unknown"),
            hosting_name=hosting_name,
            hosting_namespace=hosting_namespace,
            hosting_deployment=hosting_deployment,
            hosting_region=bounded_string(environment.get("OK_OBSERVER_HOSTING_REGION"), "unknown"),
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
        path = f"/apis/platform.openkubes.ai/v1alpha1/namespaces/{quote(namespace, safe='')}/kubevirtclusterclaims?limit=500"
        payload = self._get_json(path)
        if not isinstance(payload.get("items"), list):
            raise RuntimeError("The Kubernetes API returned an incompatible claim list.")
        return payload

    def read_hosting_cluster(self, namespace: str, deployment: str) -> dict[str, Any]:
        return {
            "version": self._get_json("/version"),
            "nodes": self._get_json("/api/v1/nodes?limit=500"),
            "deployment": self._get_json(
                f"/apis/apps/v1/namespaces/{quote(namespace, safe='')}/deployments/{quote(deployment, safe='')}"
            ),
        }

    def _get_json(self, path: str) -> dict[str, Any]:
        token = self.token_file.read_text(encoding="utf-8").strip()
        if not token:
            raise RuntimeError("The mounted ServiceAccount token is empty.")
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
                raise RuntimeError("The Kubernetes API response exceeds the response limit.")
            payload = json.loads(body)
        if not isinstance(payload, dict):
            raise RuntimeError("The Kubernetes API returned an incompatible response.")
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


def agent_deployment_projection(resources: list[dict[str, Any]], observed_at: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Project only complete, correlated AgentDeployment observations.

    This is deliberately a pure projection boundary. It does not infer a
    deployment from Pods or Agent definitions and rejects incomplete evidence.
    """
    deployments: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for resource in resources:
        if not isinstance(resource, dict) or resource.get("apiVersion") != AGENT_CONTRACT_VERSION or resource.get("kind") != AGENT_DEPLOYMENT_KIND:
            raise ValueError("An observed AgentDeployment has an incompatible contract.")
        metadata = resource.get("metadata")
        spec = resource.get("spec")
        status = resource.get("status")
        if not isinstance(metadata, dict) or not isinstance(spec, dict) or not isinstance(status, dict):
            raise ValueError("An observed AgentDeployment must include metadata, spec and status.")
        name = bounded_string(metadata.get("name"), "")
        namespace = bounded_string(metadata.get("namespace"), "")
        if not name or not DNS_LABEL.fullmatch(name) or not namespace or not DNS_LABEL.fullmatch(namespace):
            raise ValueError("An observed AgentDeployment has an invalid identity.")
        agent_ref = spec.get("agentRef")
        if not isinstance(agent_ref, dict):
            raise ValueError("An observed AgentDeployment has no agentRef.")
        agent_name = bounded_string(agent_ref.get("name"), "")
        version = bounded_string(agent_ref.get("version"), "")
        digest = bounded_string(agent_ref.get("digest"), "")
        cluster = bounded_string(spec.get("clusterRef"), "")
        authority = bounded_string(spec.get("authority"), "")
        evidence_ref = bounded_string(status.get("evidenceRef"), "")
        readiness = status.get("readiness")
        if not all((agent_name, version, cluster, authority, evidence_ref)) or not AGENT_DIGEST.fullmatch(digest):
            raise ValueError("An observed AgentDeployment is missing immutable correlation data.")
        if readiness not in {"Ready", "Pending", "Unknown"}:
            raise ValueError("An observed AgentDeployment has an unsupported readiness.")
        deployment_id = f"agent-deployment-{namespace}-{name}"
        evidence_id = f"{evidence_ref}:{deployment_id}"
        deployments.append({
            "id": deployment_id,
            "name": name,
            "agentId": agent_name,
            "agentName": agent_name,
            "version": version,
            "cluster": cluster,
            "namespace": namespace,
            "readiness": readiness,
            "authority": authority,
            "evidenceId": evidence_id,
            "digest": digest,
        })
        evidence.append({
            "id": evidence_id,
            "title": f"{agent_name} deployment observation",
            "type": "Observation",
            "outcome": readiness,
            "clusterId": cluster,
            "contract": f"{AGENT_DEPLOYMENT_KIND}/{AGENT_CONTRACT_VERSION.split('/')[-1]}",
            "revision": bounded_string(metadata.get("resourceVersion"), "unknown"),
            "observedAt": observed_at,
            "source": "OpenKubes AgentDeployment producer",
            "summary": f"Observed immutable {agent_name} deployment evidence on {cluster}.",
            "classification": "Current",
        })
    deployments.sort(key=lambda item: item["id"])
    evidence.sort(key=lambda item: item["id"])
    return deployments, evidence


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


def non_negative_integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def node_readiness(nodes: dict[str, Any]) -> tuple[str, int, int, int]:
    items = nodes.get("items")
    if not isinstance(items, list) or len(items) > 500:
        raise ValueError("The Kubernetes Node list is incompatible or exceeds the item limit.")
    ready = 0
    not_ready = 0
    unknown = 0
    for node in items:
        if not isinstance(node, dict):
            raise ValueError("Every Kubernetes Node must be an object.")
        conditions = node.get("status", {}).get("conditions", [])
        ready_status = next(
            (
                condition.get("status")
                for condition in conditions
                if isinstance(condition, dict) and condition.get("type") == "Ready"
            ),
            None,
        ) if isinstance(conditions, list) else None
        if ready_status == "True":
            ready += 1
        elif ready_status == "False":
            not_ready += 1
        else:
            unknown += 1
    if not items or unknown:
        overall = "Unknown"
    elif not_ready:
        overall = "Pending"
    else:
        overall = "Ready"
    return overall, ready, not_ready, unknown


def deployment_readiness(deployment: dict[str, Any]) -> tuple[str, int | None, int | None]:
    metadata = deployment.get("metadata", {})
    spec = deployment.get("spec", {})
    status = deployment.get("status", {})
    if not all(isinstance(value, dict) for value in (metadata, spec, status)):
        raise ValueError("The Console Deployment response is incompatible.")
    generation = non_negative_integer(metadata.get("generation"))
    observed_generation = non_negative_integer(status.get("observedGeneration"))
    desired = non_negative_integer(spec.get("replicas", 1))
    available = non_negative_integer(status.get("availableReplicas", 0))
    if None in (generation, observed_generation, desired, available) or desired == 0:
        return "Unknown", desired, available
    if observed_generation >= generation and available >= desired:
        return "Ready", desired, available
    return "Pending", desired, available


def build_hosting_cluster_state(
    observation: dict[str, Any],
    config: ProducerConfig,
    now: Callable[[], datetime] = utc_now,
) -> dict[str, Any]:
    version = observation.get("version")
    nodes = observation.get("nodes")
    deployment = observation.get("deployment")
    if not all(isinstance(value, dict) for value in (version, nodes, deployment)):
        raise ValueError("The hosting-cluster observation is incomplete.")
    observed_at = isoformat(now())
    kubernetes_version = bounded_string(version.get("gitVersion"), "unknown", 64)
    node_state, ready_nodes, not_ready_nodes, unknown_nodes = node_readiness(nodes)
    console_state, desired_replicas, available_replicas = deployment_readiness(deployment)
    if "Pending" in {node_state, console_state}:
        hosting_state = "Pending"
    elif node_state == console_state == "Ready":
        hosting_state = "Ready"
    else:
        hosting_state = "Unknown"
    node_revision = bounded_string(nodes.get("metadata", {}).get("resourceVersion"), "unknown", 128)
    deployment_revision = bounded_string(deployment.get("metadata", {}).get("resourceVersion"), "unknown", 128)
    source_revision = f"kubernetes:{kubernetes_version};nodes:{node_revision};deployment:{deployment_revision}"
    hosting_evidence_id = f"ev-{config.hosting_name}-hosting-state"
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
        "revision": "not-observed-by-hosting-source",
        "evidenceId": management_evidence_id,
        "capabilities": [],
        "lifecycle": [
            {"label": "Source boundary", "state": "Unknown", "detail": "The hosting-cluster source does not observe the OpenKubes management plane."},
            {"label": "Compositions", "state": "Unknown", "detail": "Composition state is outside this bounded Phase B1 source."},
        ],
    }
    hosting_cluster = {
        "id": f"cluster-{config.hosting_name}",
        "name": config.hosting_name,
        "role": "Workload cluster",
        "provider": "Kubernetes",
        "profile": "Console hosting cluster",
        "kubernetesVersion": kubernetes_version,
        "region": config.hosting_region,
        "readiness": hosting_state,
        "compatibility": "Read only",
        "contractVersion": "kubernetes.io/core+apps/v1",
        "revision": f"nodes:{node_revision};deployment:{deployment_revision}",
        "evidenceId": hosting_evidence_id,
        "capabilities": [],
        "lifecycle": [
            {"label": "Kubernetes API", "state": "Ready", "detail": "The bounded read-only Kubernetes API queries completed."},
            {"label": "Nodes", "state": node_state, "detail": f"Ready: {ready_nodes}; not ready: {not_ready_nodes}; unknown: {unknown_nodes}."},
            {"label": "Console workload", "state": console_state, "detail": f"Available replicas: {available_replicas if available_replicas is not None else 'unknown'} of {desired_replicas if desired_replicas is not None else 'unknown'}."},
            {"label": "OpenKubes Compositions", "state": "Unknown", "detail": "Composition and multi-cluster state are intentionally outside Phase B1."},
        ],
    }
    payload = {
        "apiVersion": QUERY_VERSION,
        "kind": QUERY_KIND,
        "metadata": {"observedAt": observed_at, "sourceRevision": source_revision, "partial": True},
        "data": {
            "environment": {"id": config.environment_id, "displayName": config.environment_name},
            "metrics": {
                "capabilities": {"total": 0, "ready": 0, "pending": 0, "failed": 0, "unknown": 0},
                "workloadClaims": {"total": 0, "ready": 0, "pending": 0, "failed": 0, "unknown": 0},
                "openFindings": {"total": 0, "critical": 0},
            },
            "clusters": [management_cluster, hosting_cluster],
            "placements": [],
            "evidence": [
                {
                    "id": management_evidence_id,
                    "title": "Management plane outside hosting source",
                    "type": "Observation",
                    "outcome": "Unknown",
                    "clusterId": f"cluster-{config.management_name}",
                    "contract": "Unavailable",
                    "revision": "not-observed-by-hosting-source",
                    "observedAt": observed_at,
                    "source": "OpenKubes hosting-cluster source boundary",
                    "summary": f"{config.management_name} identity is configured, but no management-plane or Composition state is observed in Phase B1.",
                    "classification": "Current",
                },
                {
                    "id": hosting_evidence_id,
                    "title": f"{config.hosting_name} hosting-cluster state",
                    "type": "Observation",
                    "outcome": hosting_state,
                    "clusterId": f"cluster-{config.hosting_name}",
                    "contract": "Kubernetes core/apps v1",
                    "revision": f"nodes:{node_revision};deployment:{deployment_revision}",
                    "observedAt": observed_at,
                    "source": "Bounded Kubernetes API projection",
                    "summary": f"Console hosting cluster: {ready_nodes} Ready Nodes; Console replicas {available_replicas if available_replicas is not None else 'unknown'}/{desired_replicas if desired_replicas is not None else 'unknown'} available.",
                    "classification": "Current",
                },
            ],
        },
    }
    external_observations = load_external_cluster_observations(config.cluster_observations_file, observed_at, allow_management=True)
    management_observation = next((item for item in external_observations if item["name"] == config.management_name), None)
    if management_observation is not None:
        management_cluster.update({
            key: management_observation[key]
            for key in ("provider", "kubernetesVersion", "region", "readiness", "revision", "evidenceId")
        })
        management_cluster["compatibility"] = "Read only"
        management_cluster["contractVersion"] = management_observation["contractVersion"]
        management_cluster["lifecycle"] = [
            {"label": "Kubernetes API", "state": "Ready", "detail": "The bounded read-only management-cluster observation completed."},
            *management_observation["lifecycle"],
            {"label": "Management capabilities", "state": "Unknown", "detail": "Management capabilities are not verified by this observation."},
        ]
        management_evidence_id = management_observation["evidenceId"]
        management_cluster["evidenceId"] = management_evidence_id
        payload["data"]["evidence"][0] = management_observation.pop("_evidence")
        external_observations = [item for item in external_observations if item["name"] != config.management_name]
    payload["data"]["clusters"].extend(external_observations)
    for cluster in payload["data"]["clusters"][2:]:
        payload["data"]["evidence"].append(cluster.pop("_evidence"))
    return payload


def load_external_cluster_observations(filename: str, observed_at: str, allow_management: bool = False) -> list[dict[str, Any]]:
    """Load bounded, operator-produced read-only cluster observations.

    This file contains observations, never credentials. Invalid or stale entries
    are omitted so the Console cannot present an unverified cluster as current.
    """
    if not filename:
        return []
    try:
        path = Path(filename)
        with path.open("rb") as source:
            body = source.read(MAX_CLUSTER_OBSERVATIONS_BYTES + 1)
        if len(body) > MAX_CLUSTER_OBSERVATIONS_BYTES:
            return []
        document = json.loads(body)
        entries = document.get("clusters") if isinstance(document, dict) else None
        if not isinstance(entries, list):
            return []
        result: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not isinstance(name, str) or not DNS_LABEL.fullmatch(name) or name == "ok-shared" or (name == "ok-mgmt" and not allow_management):
                continue
            readiness = entry.get("readiness")
            if readiness not in {"Ready", "Pending", "Failed", "Unknown"}:
                readiness = "Unknown"
            version = bounded_string(entry.get("kubernetesVersion"), "unknown", 64)
            region = bounded_string(entry.get("region"), "unknown", 128)
            revision = bounded_string(entry.get("revision"), "external-observation", 128)
            evidence_id = f"ev-{name}-external-observation"
            result.append({
                "id": f"cluster-{name}", "name": name, "role": "Management plane" if name == "ok-mgmt" else "Workload cluster",
                "provider": bounded_string(entry.get("provider"), "Kubernetes"),
                "profile": bounded_string(entry.get("profile"), "External workload cluster"),
                "kubernetesVersion": version, "region": region, "readiness": readiness,
                "compatibility": "Read only", "contractVersion": "kubernetes.io/core+apps/v1",
                "revision": revision, "evidenceId": evidence_id, "capabilities": [],
                "lifecycle": [{"label": "External observation", "state": readiness,
                               "detail": "Operator-provided read-only cluster observation."}],
                "_evidence": {"id": evidence_id, "title": f"{name} external cluster observation",
                              "type": "Observation", "outcome": readiness,
                              "clusterId": f"cluster-{name}", "contract": "Kubernetes core/apps v1",
                              "revision": revision, "observedAt": safe_timestamp(entry.get("observedAt"), observed_at),
                              "source": "Operator-provided read-only observation bundle",
                              "summary": f"{name}: Kubernetes {version}; readiness {readiness}.", "classification": "Current"},
            })
        return result
    except (OSError, ValueError, RecursionError):
        return []


class OwnershipError(ValueError):
    def __init__(self, object_key: str) -> None:
        # Only canonical source keys belong in diagnostics, never map values or file text.
        self.object_key = re.sub(r"[^a-zA-Z0-9/_.-]", "?", object_key)[:256]
        super().__init__("An observed object has no valid operator allocation.")


def load_ownership_file(filename: str) -> dict[str, str] | None:
    try:
        path = Path(filename)
        if not filename or not path.is_file():
            return None
        with path.open("rb") as source:
            body = source.read(MAX_OWNERSHIP_FILE_BYTES + 1)
        if len(body) > MAX_OWNERSHIP_FILE_BYTES:
            return None
        allocation = json.loads(body)
        if not isinstance(allocation, dict) or set(allocation) != {"tenants"}:
            return None
        tenants = allocation["tenants"]
        if not isinstance(tenants, dict):
            return None
        for tenant in tenants.values():
            if bounded_string(tenant, "") == "" or not tenant.strip() or tenant != tenant.strip():
                return None
        return tenants
    except (OSError, ValueError, RecursionError):
        return None


def ownership_projection(
    payload: dict[str, Any], config: ProducerConfig, tenants: dict[str, str] | None,
) -> dict[str, Any]:
    result = copy.deepcopy(payload)
    result["apiVersion"] = QUERY_V2_VERSION
    data = result["data"]
    owners: dict[str, dict[str, str]] = {}
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    # Global metrics have no per-object owner. Copying a non-zero count into every bucket would show
    # each tenant the total of all tenants, so only all-zero or unavailable values may be bucketed.
    for category, values in data["metrics"].items():
        if any(value not in (0, None) for value in values.values()):
            raise OwnershipError(f"metrics/{category}")
    for cluster in data["clusters"]:
        cluster_id = cluster["id"]
        if cluster_id == f"cluster-{config.management_name}":
            object_key = f"management/{config.management_name}"
        elif config.source_mode == "hosting-cluster" and cluster_id == f"cluster-{config.hosting_name}":
            object_key = f"hosting/{config.hosting_name}"
        elif config.source_mode == "hosting-cluster" and cluster_id.startswith("cluster-"):
            name = cluster_id[len("cluster-"):]
            if not DNS_LABEL.fullmatch(name):
                raise OwnershipError(cluster_id)
            object_key = f"external/{name}"
        elif config.source_mode == "kubevirt-claims" and cluster_id.startswith("cluster-"):
            name = cluster_id[len("cluster-"):]
            if not DNS_LABEL.fullmatch(name):
                raise OwnershipError(cluster_id)
            object_key = f"claim/{config.namespace}/{name}"
        else:
            raise OwnershipError(cluster_id)
        tenant = tenants.get(object_key) if tenants is not None else None
        if bounded_string(tenant, "") == "" or not tenant.strip() or tenant != tenant.strip():
            raise OwnershipError(object_key)
        if cluster_id in owners:
            raise OwnershipError(object_key)
        owner = {"environmentId": data.get("environment", {}).get("id", config.environment_id), "tenantId": tenant}
        owners[cluster_id] = owner
        cluster["ownership"] = owner.copy()
        for capability in cluster["capabilities"]:
            capability["ownership"] = owner.copy()
        ownership_tuple = (owner["environmentId"], owner["tenantId"])
        if ownership_tuple not in buckets:
            # Both sources expose only empty, partial metric projections. Preserve
            # that coverage boundary, including any unavailable (None) values.
            buckets[ownership_tuple] = {"ownership": owner.copy(), **copy.deepcopy(data["metrics"])}
    for evidence in data["evidence"]:
        cluster_id = evidence["clusterId"]
        if cluster_id not in owners:
            raise OwnershipError(cluster_id)
        evidence["ownership"] = owners[cluster_id].copy()
    for placement in data["placements"]:
        cluster_id = placement.get("targetClusterId", "missing-targetClusterId")
        if cluster_id not in owners:
            raise OwnershipError(cluster_id)
        placement["ownership"] = owners[cluster_id].copy()
    data["metrics"] = list(buckets.values())
    return result


class ObservedStateProducer:
    def __init__(self, client: KubernetesApiClient, config: ProducerConfig, now: Callable[[], datetime] = utc_now) -> None:
        self.client = client
        self.config = config
        self.now = now
        self.tenants = load_ownership_file(config.ownership_file)

    def snapshot_v2(self) -> dict[str, Any]:
        return ownership_projection(self.snapshot(), self.config, self.tenants)

    def snapshot(self) -> dict[str, Any]:
        if self.config.source_mode == "hosting-cluster":
            observation = self.client.read_hosting_cluster(
                self.config.hosting_namespace,
                self.config.hosting_deployment,
            )
            return build_hosting_cluster_state(observation, self.config, self.now)
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
            version = QUERY_V2_VERSION if self.path == QUERY_V2_PATH else QUERY_VERSION
            self.send_header("Content-Type", f'application/json; profile="{version}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/healthz":
                self.send_json(200, {"status": "ok"})
                return
            if self.path not in {QUERY_PATH, QUERY_V2_PATH}:
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
                payload = producer.snapshot_v2() if self.path == QUERY_V2_PATH else producer.snapshot()
                self.send_json(200, payload)
            except OwnershipError as error:
                print(f"observed-state-producer ownership unavailable key={error.object_key}")
                self.send_json(503, {"error": "source_unavailable", "retryable": True})
            except Exception as error:
                # Keep the client response deliberately generic, but leave a
                # bounded type-only diagnostic for operators. Never print the
                # exception text because it may contain source or credential data.
                print(f"observed-state-producer source unavailable error={type(error).__name__}")
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
