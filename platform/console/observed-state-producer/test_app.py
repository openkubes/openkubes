import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

from app import (
    QUERY_KIND,
    QUERY_PATH,
    QUERY_VERSION,
    KubernetesApiClient,
    ObservedStateProducer,
    ProducerConfig,
    TlsConfig,
    build_hosting_cluster_state,
    build_observed_state,
    handler_for,
)


NOW = datetime(2026, 8, 21, 18, 30, tzinfo=timezone.utc)


def claim(name="ok-ai", ready="True", resource_version="17"):
    return {
        "apiVersion": "platform.openkubes.ai/v1alpha1",
        "kind": "KubeVirtClusterClaim",
        "metadata": {"name": name, "namespace": "openkubes-system", "resourceVersion": resource_version},
        "spec": {"provider": "kubevirt", "country": "de", "controlPlane": {"kubernetesVersion": "v1.34.1"}},
        "status": {"conditions": [{"type": "Ready", "status": ready, "reason": "IgnoredBackendReason", "message": "private backend diagnostic", "lastTransitionTime": "2026-08-21T18:29:00Z"}]},
    }


def claim_list(*items):
    return {"apiVersion": "v1", "kind": "KubeVirtClusterClaimList", "metadata": {"resourceVersion": "84"}, "items": list(items)}


def hosting_observation(node_statuses=("True", "True"), available_replicas=2, observed_generation=7):
    return {
        "version": {"gitVersion": "v1.34.1", "platform": "linux/amd64", "privateDiagnostic": "must not pass"},
        "nodes": {
            "metadata": {"resourceVersion": "211"},
            "items": [
                {
                    "metadata": {"name": f"private-node-{index}"},
                    "status": {"conditions": [{"type": "Ready", "status": status, "message": "private node detail"}]},
                }
                for index, status in enumerate(node_statuses)
            ],
        },
        "deployment": {
            "metadata": {"name": "ok-console", "namespace": "openkubes-console", "generation": 7, "resourceVersion": "377"},
            "spec": {"replicas": 2, "template": {"spec": {"containers": [{"env": [{"name": "SECRET", "value": "private"}]}]}}},
            "status": {"observedGeneration": observed_generation, "availableReplicas": available_replicas, "conditions": [{"message": "private rollout detail"}]},
        },
    }


class ProjectionTests(unittest.TestCase):
    def test_projects_real_claim_conditions_without_backend_diagnostics(self):
        payload = build_observed_state(claim_list(claim()), ProducerConfig(), now=lambda: NOW)

        self.assertEqual(payload["apiVersion"], QUERY_VERSION)
        self.assertEqual(payload["kind"], QUERY_KIND)
        self.assertTrue(payload["metadata"]["partial"])
        self.assertEqual(payload["metadata"]["sourceRevision"], "kubevirtclusterclaims:84")
        self.assertEqual([item["name"] for item in payload["data"]["clusters"]], ["ok-mgmt", "ok-ai"])
        self.assertEqual(payload["data"]["clusters"][0]["readiness"], "Unknown")
        self.assertEqual(payload["data"]["clusters"][1]["readiness"], "Ready")
        serialized = json.dumps(payload)
        self.assertNotIn("private backend diagnostic", serialized)
        self.assertNotIn("IgnoredBackendReason", serialized)

    def test_keeps_false_and_missing_ready_conditions_non_ready(self):
        without_condition = claim("edge-07")
        without_condition["status"] = {}
        payload = build_observed_state(claim_list(claim("ok-shared", "False"), without_condition), ProducerConfig(), now=lambda: NOW)
        readiness = {item["name"]: item["readiness"] for item in payload["data"]["clusters"]}

        self.assertEqual(readiness["ok-shared"], "Pending")
        self.assertEqual(readiness["edge-07"], "Unknown")

    def test_management_plane_is_never_declared_ready_from_api_reachability(self):
        payload = build_observed_state(claim_list(), ProducerConfig(), now=lambda: NOW)
        management = payload["data"]["clusters"][0]

        self.assertEqual(management["role"], "Management plane")
        self.assertEqual(management["readiness"], "Unknown")
        self.assertEqual(management["compatibility"], "Read only")
        self.assertEqual(management["contractVersion"], "unknown")

    def test_rejects_invalid_claim_identity(self):
        invalid = claim()
        invalid["metadata"]["name"] = "../../secret"
        with self.assertRaisesRegex(ValueError, "invalid metadata.name"):
            build_observed_state(claim_list(invalid), ProducerConfig(), now=lambda: NOW)

    def test_rejects_a_claim_that_collides_with_the_management_plane(self):
        with self.assertRaisesRegex(ValueError, "distinct from the management plane"):
            build_observed_state(claim_list(claim("ok-mgmt")), ProducerConfig(), now=lambda: NOW)

    def test_invalid_condition_timestamp_falls_back_to_observation_time(self):
        item = claim()
        item["status"]["conditions"][0]["lastTransitionTime"] = "not-a-timestamp"
        payload = build_observed_state(claim_list(item), ProducerConfig(), now=lambda: NOW)
        claim_evidence = payload["data"]["evidence"][1]

        self.assertEqual(claim_evidence["observedAt"], "2026-08-21T18:30:00Z")


class HostingClusterProjectionTests(unittest.TestCase):
    def test_projects_only_bounded_hosting_cluster_state(self):
        config = ProducerConfig(
            source_mode="hosting-cluster",
            environment_id="ok-shared-dev",
            environment_name="OpenKubes shared development",
            hosting_name="ok-shared",
            hosting_region="fra-dc1",
        )
        payload = build_hosting_cluster_state(hosting_observation(), config, now=lambda: NOW)

        self.assertEqual(payload["metadata"], {
            "observedAt": "2026-08-21T18:30:00Z",
            "sourceRevision": "kubernetes:v1.34.1;nodes:211;deployment:377",
            "partial": True,
        })
        self.assertEqual([item["name"] for item in payload["data"]["clusters"]], ["ok-mgmt", "ok-shared"])
        self.assertEqual(payload["data"]["clusters"][0]["readiness"], "Unknown")
        hosting = payload["data"]["clusters"][1]
        self.assertEqual(hosting["role"], "Workload cluster")
        self.assertEqual(hosting["profile"], "Console hosting cluster")
        self.assertEqual(hosting["readiness"], "Ready")
        self.assertEqual(hosting["kubernetesVersion"], "v1.34.1")
        self.assertIn("Ready: 2; not ready: 0; unknown: 0", hosting["lifecycle"][1]["detail"])
        serialized = json.dumps(payload)
        for forbidden in ("private-node", "private node detail", "private rollout detail", "privateDiagnostic", '"SECRET"'):
            self.assertNotIn(forbidden, serialized)

    def test_reports_bounded_non_ready_and_unknown_states(self):
        config = ProducerConfig(source_mode="hosting-cluster")
        pending = build_hosting_cluster_state(
            hosting_observation(node_statuses=("True", "False"), available_replicas=1),
            config,
            now=lambda: NOW,
        )
        self.assertEqual(pending["data"]["clusters"][1]["readiness"], "Pending")

        unknown = build_hosting_cluster_state(
            hosting_observation(node_statuses=(), available_replicas=2),
            config,
            now=lambda: NOW,
        )
        self.assertEqual(unknown["data"]["clusters"][1]["readiness"], "Unknown")

    def test_requires_explicit_valid_and_distinct_source_identity(self):
        config = ProducerConfig.from_environment({
            "OK_OBSERVER_SOURCE_MODE": "hosting-cluster",
            "OK_OBSERVER_HOSTING_NAME": "ok-shared",
            "OK_OBSERVER_HOSTING_NAMESPACE": "openkubes-console",
            "OK_OBSERVER_HOSTING_DEPLOYMENT": "ok-console",
        })
        self.assertEqual(config.source_mode, "hosting-cluster")
        with self.assertRaisesRegex(ValueError, "kubevirt-claims or hosting-cluster"):
            ProducerConfig.from_environment({"OK_OBSERVER_SOURCE_MODE": "automatic"})
        with self.assertRaisesRegex(ValueError, "distinct from the management plane"):
            ProducerConfig.from_environment({"OK_OBSERVER_HOSTING_NAME": "ok-mgmt"})


class ApiClientTests(unittest.TestCase):
    def test_uses_namespaced_get_and_keeps_token_in_authorization_header(self):
        captured = {}

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self, _limit):
                return json.dumps(claim_list()).encode()

        def opener(request, **kwargs):
            captured["url"] = request.full_url
            captured["authorization"] = request.get_header("Authorization")
            captured["timeout"] = kwargs["timeout"]
            return Response()

        with tempfile.TemporaryDirectory() as directory:
            token_file = Path(directory) / "token"
            ca_file = Path(directory) / "ca.crt"
            token_file.write_text("server-side-token\n", encoding="utf-8")
            ca_file.write_text("", encoding="utf-8")
            client = object.__new__(KubernetesApiClient)
            client.base_url = "https://kubernetes.default.svc:443"
            client.token_file = token_file
            client.context = None
            client.timeout_seconds = 3
            client.opener = opener
            result = client.list_cluster_claims("openkubes-system")

        self.assertEqual(result["metadata"]["resourceVersion"], "84")
        self.assertIn("/namespaces/openkubes-system/kubevirtclusterclaims?limit=500", captured["url"])
        self.assertEqual(captured["authorization"], "Bearer server-side-token")
        self.assertEqual(captured["timeout"], 3)

    def test_reads_only_version_nodes_and_named_console_deployment_for_hosting_mode(self):
        captured = []

        class Response:
            status = 200

            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self, _limit):
                return json.dumps(self.payload).encode()

        def opener(request, **_kwargs):
            captured.append((request.full_url, request.get_header("Authorization")))
            if request.full_url.endswith("/version"):
                return Response({"gitVersion": "v1.34.1"})
            if "/api/v1/nodes" in request.full_url:
                return Response({"metadata": {"resourceVersion": "1"}, "items": []})
            return Response({"metadata": {"generation": 1, "resourceVersion": "2"}, "spec": {"replicas": 1}, "status": {"observedGeneration": 1, "availableReplicas": 1}})

        with tempfile.TemporaryDirectory() as directory:
            token_file = Path(directory) / "token"
            token_file.write_text("server-side-token\n", encoding="utf-8")
            client = object.__new__(KubernetesApiClient)
            client.base_url = "https://kubernetes.default.svc:443"
            client.token_file = token_file
            client.context = None
            client.timeout_seconds = 3
            client.opener = opener
            result = client.read_hosting_cluster("openkubes-console", "ok-console")

        self.assertEqual(result["version"]["gitVersion"], "v1.34.1")
        self.assertEqual([url.removeprefix("https://kubernetes.default.svc:443") for url, _token in captured], [
            "/version",
            "/api/v1/nodes?limit=500",
            "/apis/apps/v1/namespaces/openkubes-console/deployments/ok-console",
        ])
        self.assertTrue(all(token == "Bearer server-side-token" for _url, token in captured))


class TlsConfigurationTests(unittest.TestCase):
    def test_requires_bounded_mounted_tls_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("server.crt", "server.key", "client-ca.crt"):
                (root / name).write_text("test-only-material", encoding="utf-8")
            config = TlsConfig.from_environment({
                "OK_OBSERVER_TLS_CERT_FILE": str(root / "server.crt"),
                "OK_OBSERVER_TLS_KEY_FILE": str(root / "server.key"),
                "OK_OBSERVER_TLS_CLIENT_CA_FILE": str(root / "client-ca.crt"),
                "OK_OBSERVER_TLS_CLIENT_IDENTITY": "spiffe://openkubes.io/ns/openkubes-console/sa/ok-console-bff",
            })

        self.assertEqual(config.certificate_file.name, "server.crt")
        self.assertEqual(config.private_key_file.name, "server.key")
        self.assertEqual(config.client_ca_file.name, "client-ca.crt")
        self.assertEqual(config.expected_client_identity, "spiffe://openkubes.io/ns/openkubes-console/sa/ok-console-bff")

    def test_rejects_missing_or_empty_tls_material(self):
        with self.assertRaisesRegex(ValueError, "Missing required TLS"):
            TlsConfig.from_environment({})
        with tempfile.TemporaryDirectory() as directory:
            empty = Path(directory) / "empty"
            empty.touch()
            with self.assertRaisesRegex(ValueError, "between 1 and"):
                TlsConfig.from_environment({
                    "OK_OBSERVER_TLS_CERT_FILE": str(empty),
                    "OK_OBSERVER_TLS_KEY_FILE": str(empty),
                    "OK_OBSERVER_TLS_CLIENT_CA_FILE": str(empty),
                    "OK_OBSERVER_TLS_CLIENT_IDENTITY": "spiffe://openkubes.io/ns/openkubes-console/sa/ok-console-bff",
                })


class HttpBoundaryTests(unittest.TestCase):
    def setUp(self):
        class Client:
            def list_cluster_claims(self, _namespace):
                return claim_list(claim())

        producer = ObservedStateProducer(Client(), ProducerConfig(), now=lambda: NOW)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(producer, require_client_identity=False))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        connection.request(method, path)
        response = connection.getresponse()
        body = json.loads(response.read())
        connection.close()
        return response, body

    def test_serves_only_the_versioned_read_only_query(self):
        response, body = self.request("GET", QUERY_PATH)
        self.assertEqual(response.status, 200)
        self.assertEqual(body["kind"], QUERY_KIND)
        self.assertEqual(response.getheader("Cache-Control"), "no-store")

        mutation, mutation_body = self.request("POST", QUERY_PATH)
        self.assertEqual(mutation.status, 405)
        self.assertEqual(mutation_body, {"error": "method_not_allowed"})

        unknown, unknown_body = self.request("GET", "/api/v1/secrets")
        self.assertEqual(unknown.status, 404)
        self.assertEqual(unknown_body, {"error": "not_found"})

    def test_returns_a_bounded_error_without_exception_details(self):
        class FailingClient:
            def list_cluster_claims(self, _namespace):
                raise RuntimeError("token and private Kubernetes details")

        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        producer = ObservedStateProducer(FailingClient(), ProducerConfig(), now=lambda: NOW)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(producer, require_client_identity=False))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        response, body = self.request("GET", QUERY_PATH)

        self.assertEqual(response.status, 503)
        self.assertEqual(body, {"error": "source_unavailable", "retryable": True})
        self.assertNotIn("token", json.dumps(body))


if __name__ == "__main__":
    unittest.main()
