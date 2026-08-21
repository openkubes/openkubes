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


class HttpBoundaryTests(unittest.TestCase):
    def setUp(self):
        class Client:
            def list_cluster_claims(self, _namespace):
                return claim_list(claim())

        producer = ObservedStateProducer(Client(), ProducerConfig(), now=lambda: NOW)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(producer))
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
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(producer))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        response, body = self.request("GET", QUERY_PATH)

        self.assertEqual(response.status, 503)
        self.assertEqual(body, {"error": "source_unavailable", "retryable": True})
        self.assertNotIn("token", json.dumps(body))


if __name__ == "__main__":
    unittest.main()
