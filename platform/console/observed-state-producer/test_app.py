import io
import inspect
import json
from contextlib import redirect_stdout
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
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
    agent_deployment_projection,
    build_hosting_cluster_state,
    build_observed_state,
    external_timestamp,
    handler_for,
    load_external_cluster_observations,
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
    def test_projects_only_correlated_agent_deployment_evidence(self):
        resources = [{
            "apiVersion": "agents.openkubes.io/v1alpha1",
            "kind": "AgentDeployment",
            "metadata": {"name": "docs-search", "namespace": "openkubes-agents", "resourceVersion": "9"},
            "spec": {
                "agentRef": {"name": "ok-ai-document-search", "version": "beta-1.1", "digest": "sha256:" + "a" * 64},
                "clusterRef": "ok-shared",
                "authority": "read-only",
            },
            "status": {"readiness": "Ready", "evidenceRef": "agent-deploy/ns/name"},
        }]
        deployments, evidence = agent_deployment_projection(resources, "2026-08-21T18:30:00Z")

        self.assertEqual(deployments[0]["cluster"], "ok-shared")
        self.assertEqual(deployments[0]["digest"], "sha256:" + "a" * 64)
        self.assertEqual(deployments[0]["evidenceId"], evidence[0]["id"])
        self.assertEqual(evidence[0]["outcome"], "Ready")

    def test_rejects_agent_pod_like_or_incomplete_observation(self):
        with self.assertRaisesRegex(ValueError, "agentRef"):
            agent_deployment_projection([{
                "apiVersion": "agents.openkubes.io/v1alpha1",
                "kind": "AgentDeployment",
                "metadata": {"name": "docs-search", "namespace": "openkubes-agents"},
                "spec": {"clusterRef": "ok-shared"},
                "status": {},
            }], "2026-08-21T18:30:00Z")

    def test_projects_real_claim_conditions_without_backend_diagnostics(self):
        payload = build_observed_state(claim_list(claim()), ProducerConfig(), now=lambda: NOW, read_started_at="2026-08-21T18:30:00Z")

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
        payload = build_observed_state(claim_list(claim("ok-shared", "False"), without_condition), ProducerConfig(), now=lambda: NOW, read_started_at="2026-08-21T18:30:00Z")
        readiness = {item["name"]: item["readiness"] for item in payload["data"]["clusters"]}

        self.assertEqual(readiness["ok-shared"], "Pending")
        self.assertEqual(readiness["edge-07"], "Unknown")

    def test_management_plane_is_never_declared_ready_from_api_reachability(self):
        payload = build_observed_state(claim_list(), ProducerConfig(), now=lambda: NOW, read_started_at="2026-08-21T18:30:00Z")
        management = payload["data"]["clusters"][0]

        self.assertEqual(management["role"], "Management plane")
        self.assertEqual(management["readiness"], "Unknown")
        self.assertEqual(management["compatibility"], "Read only")
        self.assertEqual(management["contractVersion"], "unknown")

    def test_rejects_invalid_claim_identity(self):
        invalid = claim()
        invalid["metadata"]["name"] = "../../secret"
        with self.assertRaisesRegex(ValueError, "invalid metadata.name"):
            build_observed_state(claim_list(invalid), ProducerConfig(), now=lambda: NOW, read_started_at="2026-08-21T18:30:00Z")

    def test_rejects_a_claim_that_collides_with_the_management_plane(self):
        with self.assertRaisesRegex(ValueError, "distinct from the management plane"):
            build_observed_state(claim_list(claim("ok-mgmt")), ProducerConfig(), now=lambda: NOW, read_started_at="2026-08-21T18:30:00Z")

    def test_invalid_condition_timestamp_falls_back_to_observation_time(self):
        item = claim()
        item["status"]["conditions"][0]["lastTransitionTime"] = "not-a-timestamp"
        payload = build_observed_state(claim_list(item), ProducerConfig(), now=lambda: NOW, read_started_at="2026-08-21T18:30:00Z")
        claim_evidence = payload["data"]["evidence"][1]

        self.assertEqual(claim_evidence["observedAt"], "2026-08-21T18:30:00Z")


class HostingClusterProjectionTests(unittest.TestCase):
    def test_projects_workloads_with_replica_evidence_and_no_container_secrets(self):
        observation = hosting_observation()
        observation["workloads"] = [observation["deployment"]]
        config = ProducerConfig(source_mode="hosting-cluster", workload_deployments=("ok-console",))
        payload = build_hosting_cluster_state(observation, config, now=lambda: NOW, read_started_at="2026-08-21T18:30:00Z", workload_read_times={"ok-console": "2026-08-21T18:30:00Z"})
        placement = payload["data"]["placements"][0]
        self.assertEqual(placement["name"], "openkubes-console/ok-console")
        self.assertEqual(placement["readiness"], "Ready")
        evidence = next(item for item in payload["data"]["evidence"] if item["id"] == placement["evidenceId"])
        self.assertIn("replicas:2/2", evidence["revision"])
        self.assertNotIn('"SECRET"', json.dumps(payload))
        observation["workloads"][0]["status"]["observedGeneration"] = 6
        self.assertEqual(build_hosting_cluster_state(observation, config, now=lambda: NOW, read_started_at="2026-08-21T18:30:00Z", workload_read_times={"ok-console": "2026-08-21T18:30:00Z"})["data"]["placements"][0]["readiness"], "Pending")
        with self.assertRaisesRegex(ValueError, "outside the configured"):
            build_hosting_cluster_state(observation, ProducerConfig(), now=lambda: NOW, read_started_at="2026-08-21T18:30:00Z", workload_read_times={"ok-console": "2026-08-21T18:30:00Z"})

    def test_external_infrastructure_profile_projects_as_infrastructure_plane(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "observations.json"
            path.write_text(json.dumps({"clusters": [{
                "name": "ok-infra", "profile": "Infrastructure host cluster",
                "observedAt": "2026-08-21T18:29:00Z",
                "readiness": "Ready", "kubernetesVersion": "v1.35.5+rke2r1",
            }]}), encoding="utf-8")
            observed = load_external_cluster_observations(str(path), "2026-08-21T18:30:00Z")
        self.assertEqual(observed[0]["role"], "Infrastructure plane")

    def test_projects_only_bounded_hosting_cluster_state(self):
        config = ProducerConfig(
            source_mode="hosting-cluster",
            environment_id="ok-shared-dev",
            environment_name="OpenKubes shared development",
            hosting_name="ok-shared",
            hosting_region="fra-dc1",
        )
        payload = build_hosting_cluster_state(hosting_observation(), config, now=lambda: NOW, read_started_at="2026-08-21T18:30:00Z", workload_read_times={"ok-console": "2026-08-21T18:30:00Z"})

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
            read_started_at="2026-08-21T18:30:00Z", workload_read_times={"ok-console": "2026-08-21T18:30:00Z"},
        )
        self.assertEqual(pending["data"]["clusters"][1]["readiness"], "Pending")

        unknown = build_hosting_cluster_state(
            hosting_observation(node_statuses=(), available_replicas=2),
            config,
            now=lambda: NOW,
            read_started_at="2026-08-21T18:30:00Z", workload_read_times={"ok-console": "2026-08-21T18:30:00Z"},
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


class ObservationTimeTests(unittest.TestCase):
    def test_external_timestamp_scales_fractions_at_future_limit(self):
        evaluated_at = "2026-08-21T18:30:00.5Z"
        self.assertIsNone(external_timestamp("2026-08-21T18:31:00.6Z", evaluated_at))
        # Equivalent fractions with different precision must both stay 59.9s ahead.
        for value in ("2026-08-21T18:31:00.4Z", "2026-08-21T18:31:00.40Z"):
            with self.subTest(observedAt=value):
                self.assertEqual(external_timestamp(value, evaluated_at), value)

    def test_external_timestamp_validation_and_management_boundary(self):
        invalid = [None, False, 42, [], {}, "", "2026-08-21", "2026-08-21T18:30:00",
                   "2026-08-21 18:30:00Z", "2026-W34-5T18:30:00Z",
                   "2026-08-21T18:30:00.1234567Z", "2026-08-21T18:30:00.0000000Z", "2026-02-30T18:30:00Z",
                   "2026-08-21T18:30:00+24:00", "2026-08-21T18:30:00+00:60",
                   "2026-08-21T18:30:00+14:01", "2026-08-21T18:30:00+15:00", "2026-08-21T18:30:00-14:01",
                   "2026-08-21T18:30:00+00:00:00", "2026-08-21t18:30:00Z",
                   "2026-08-21T18:30:00z", "2026-08-21T23:59:60Z",
                   "2026-08-21T18:30:00Ztrailing", "2026-08-21T18:30:00Z\n", "2026-08-21T18:31:00.000001Z"]
        valid = ["2026-08-21T18:30:00Z", "2026-08-21T20:30:00+02:00",
                 "2026-08-21T16:30:00-02:00", "2026-08-21T18:30:00.123456Z",
                 "2026-08-21T18:30:00.5Z", "2026-08-21T18:30:00.1234Z",
                 "2026-08-21T18:30:00+14:00", "2000-01-01T00:00:00-14:00",
                 "2026-08-21T18:30:00-00:00",
                 "2026-08-21T18:31:00Z", "2000-01-01T00:00:00Z"]
        absent = object()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "observations.json"
            config = ProducerConfig(source_mode="hosting-cluster", cluster_observations_file=str(path))
            for name in ("ok-infra", "ok-mgmt"):
                for value in [absent, *invalid, *valid]:
                    with self.subTest(name=name, observedAt=value):
                        entry = {"name": name, "readiness": "Ready"}
                        if value is not absent:
                            entry["observedAt"] = value
                        path.write_text(json.dumps({"clusters": [entry]}), encoding="utf-8")
                        payload = build_hosting_cluster_state(hosting_observation(), config, now=lambda: NOW, read_started_at="2026-08-21T18:30:00Z", workload_read_times={"ok-console": "2026-08-21T18:30:00Z"})
                        matching = [item for item in payload["data"]["evidence"]
                                    if item["id"] == f"ev-{name}-external-observation"]
                        if isinstance(value, str) and value in valid:
                            self.assertEqual(len(matching), 1)
                            self.assertEqual(matching[0]["observedAt"], value)
                        else:
                            self.assertEqual(matching, [])
                            management = payload["data"]["clusters"][0]
                            self.assertEqual(management["readiness"], "Unknown")
                            self.assertEqual(management["evidenceId"], "ev-ok-mgmt-source-boundary")

    def test_mixed_bundle_keeps_management_and_signals_each_dropped_entry(self):
        good = {"name": "ok-mgmt", "readiness": "Ready", "observedAt": "2000-01-01T00:00:00Z"}
        absent = object()
        cases = [(None, "unknown", "invalid-entry"), ([], "unknown", "invalid-entry")]
        for name in (None, [], "", "bad\nname", "x" * 200 + "\n"):
            safe_name = "unknown" if not isinstance(name, str) else name[:63].replace("\n", "?")
            cases.append(({**good, "name": name}, safe_name, "invalid-name"))
        for name in ("ok-shared", "../foreign"):
            cases.append(({**good, "name": name}, name.replace("/", "?"), "invalid-name"))
        for value in (absent, None, [], {}, 1, False, "private-value", "2026-02-30T00:00:00Z",
                      "2026-08-21T18:30:00+14:01", "2026-08-21T18:30:00+15:00", "2026-08-21T18:30:00+00:00:00",
                      "2026-08-21t18:30:00Z", "2026-08-21T18:30:00z",
                      "2026-08-21T23:59:60Z", "2026-08-21T18:30:00.1234567Z", "2026-08-21T18:30:00.0000000Z",
                      "2026-08-21T18:30:00Ztrailing", "2026-08-21T18:31:00.000001Z"):
            entry = {**good, "name": "invalid-time"}
            if value is absent:
                entry.pop("observedAt")
            else:
                entry["observedAt"] = value
            cases.append((entry, "invalid-time", "invalid-timestamp"))
        for value in (absent, None, [], {}, 1, False):
            entry = {**good, "name": "invalid-readiness"}
            if value is absent:
                entry.pop("readiness")
            else:
                entry["readiness"] = value
            cases.append((entry, "invalid-readiness", "invalid-readiness"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "observations.json"
            config = ProducerConfig(source_mode="hosting-cluster", cluster_observations_file=str(path))
            for entry, safe_name, reason in cases:
                for entries in ([entry, good], [good, entry]):
                    with self.subTest(entry=entry, management_first=entries[0] is good):
                        path.write_text(json.dumps({"clusters": entries}), encoding="utf-8")
                        output = io.StringIO()
                        with redirect_stdout(output):
                            payload = build_hosting_cluster_state(
                                hosting_observation(), config, now=lambda: NOW,
                                read_started_at="2026-08-21T18:29:00Z", workload_read_times={},
                            )
                        self.assertEqual(output.getvalue().splitlines(), [
                            f"external-observation-dropped name={safe_name} reason={reason}"
                        ])
                        self.assertLessEqual(len(safe_name), 63)
                        self.assertNotIn("private-value", output.getvalue())
                        self.assertEqual([c["name"] for c in payload["data"]["clusters"]], ["ok-mgmt", "ok-shared"])
                        management = payload["data"]["clusters"][0]
                        self.assertEqual(management["readiness"], "Ready")
                        evidence = payload["data"]["evidence"][0]
                        self.assertEqual(evidence["id"], management["evidenceId"])
                        self.assertEqual(evidence["id"], "ev-ok-mgmt-external-observation")
                        self.assertEqual(evidence["observedAt"], good["observedAt"])

    def test_read_times_are_required_keywords_and_missing_workload_time_fails(self):
        for function, names in ((build_observed_state, ("read_started_at",)),
                                (build_hosting_cluster_state, ("read_started_at", "workload_read_times"))):
            for name in names:
                parameter = inspect.signature(function).parameters[name]
                self.assertEqual(parameter.kind, inspect.Parameter.KEYWORD_ONLY)
                self.assertIs(parameter.default, inspect.Parameter.empty)
        observation = hosting_observation()
        observation["workloads"] = [observation["deployment"]]
        with self.assertRaises(KeyError):
            build_hosting_cluster_state(
                observation, ProducerConfig(workload_deployments=("ok-console",)), now=lambda: NOW,
                read_started_at="2026-08-21T18:29:00Z", workload_read_times={},
            )

    def test_claim_evidence_uses_list_read_start_for_every_transition_value(self):
        absent = object()
        for value in (absent, None, False, 42, [], {}, "2026-08-21", "2026-08-21T18:30:00",
                      "2026-08-21 18:30:00Z", "2026-08-21T18:30:00.1234567Z", "2026-08-21T18:30:00.0000000Z",
                      "2026-08-21T18:32:00Z", "2000-01-01T00:00:00Z", "2026-08-21T18:29:00Z"):
            with self.subTest(lastTransitionTime=value):
                instant = [NOW]
                item = claim()
                condition = item["status"]["conditions"][0]
                condition.pop("lastTransitionTime")
                if value is not absent:
                    condition["lastTransitionTime"] = value

                class Client:
                    def list_cluster_claims(self, _namespace):
                        instant[0] += timedelta(seconds=10)
                        return claim_list(item)

                payload = ObservedStateProducer(Client(), ProducerConfig(), now=lambda: instant[0]).snapshot()
                evidence = next(e for e in payload["data"]["evidence"] if e["id"] == "ev-ok-ai-claim-readiness")
                self.assertEqual(evidence["observedAt"], "2026-08-21T18:30:00Z")
                self.assertEqual(payload["data"]["evidence"][0]["observedAt"], "2026-08-21T18:30:00Z")
                self.assertEqual(payload["metadata"]["observedAt"], "2026-08-21T18:30:10Z")

    def test_hosting_and_each_workload_use_their_own_read_start(self):
        instant = [NOW]

        class Client:
            def read_hosting_cluster(self, _namespace, _deployment):
                instant[0] += timedelta(seconds=10)
                return hosting_observation()

            def read_workload_deployment(self, namespace, name):
                resource = hosting_observation()["deployment"]
                resource["metadata"].update(name=name, namespace=namespace)
                instant[0] += timedelta(seconds=10)
                return resource

        config = ProducerConfig(source_mode="hosting-cluster", workload_deployments=("ok-console", "worker"))
        payload = ObservedStateProducer(Client(), config, now=lambda: instant[0]).snapshot()
        times = {e["id"]: e["observedAt"] for e in payload["data"]["evidence"]}
        self.assertEqual(times["ev-ok-mgmt-source-boundary"], "2026-08-21T18:30:00Z")
        self.assertEqual(times["ev-ok-shared-hosting-state"], "2026-08-21T18:30:00Z")
        self.assertEqual(times["ev-observed-deployment-openkubes-console-ok-console"], "2026-08-21T18:30:10Z")
        self.assertEqual(times["ev-observed-deployment-openkubes-console-worker"], "2026-08-21T18:30:20Z")
        self.assertEqual(payload["metadata"]["observedAt"], "2026-08-21T18:30:30Z")


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


class OwnershipGuardTests(unittest.TestCase):
    def test_file_validation_guards(self):
        from app import load_ownership_file
        cases = (
            b'{not-json',
            b'{"tenants":{}}' + b' ' * (64 * 1024),
            b'{"tenants":{},"environmentId":"forged"}',
            b'{"tenants":[]}',
            b'{"tenants":{"claim/openkubes-system/a":""}}',
            b'{"tenants":{"claim/openkubes-system/a":false}}',
            b'[' * 2000 + b'0' + b']' * 2000,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "allocation.json"
            for content in cases:
                with self.subTest(content=content[:50]):
                    path.write_bytes(content)
                    self.assertIsNone(load_ownership_file(str(path)))

    def test_nonregular_ownership_file_is_not_opened(self):
        from unittest.mock import patch
        from app import load_ownership_file
        with patch("app.Path.is_file", return_value=False), patch("app.Path.open") as opener:
            self.assertIsNone(load_ownership_file("not-a-regular-file"))
            opener.assert_not_called()

    def test_projection_rejects_unknown_and_duplicate_object_references(self):
        import copy
        from app import ownership_projection
        config = ProducerConfig()
        tenants = {"management/ok-mgmt": "a", "claim/openkubes-system/ok-ai": "b", "claim/openkubes-system/../x": "b"}
        original = build_observed_state(claim_list(claim()), config, now=lambda: NOW, read_started_at="2026-08-21T18:30:00Z")
        variants = []
        duplicate = copy.deepcopy(original)
        duplicate["data"]["clusters"].append(copy.deepcopy(duplicate["data"]["clusters"][1]))
        variants.append(duplicate)
        invalid_name = copy.deepcopy(original)
        invalid_name["data"]["clusters"][1]["id"] = "cluster-../x"
        variants.append(invalid_name)
        unknown_cluster = copy.deepcopy(original)
        unknown_cluster["data"]["clusters"][1]["id"] = "unexpected-id"
        variants.append(unknown_cluster)
        evidence = copy.deepcopy(original)
        evidence["data"]["evidence"][1]["clusterId"] = "cluster-unallocated"
        variants.append(evidence)
        for placement in ({"targetClusterId": "cluster-unallocated", "targetCluster": "ok-ai"}, {"targetCluster": "ok-ai"}):
            variant = copy.deepcopy(original)
            variant["data"]["placements"] = [placement]
            variants.append(variant)
        for index, variant in enumerate(variants):
            with self.subTest(variant=index), self.assertRaises(ValueError):
                ownership_projection(variant, config, tenants)

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

    def test_v2_requires_the_same_workload_identity(self):
        class Connection:
            def getpeercert(self):
                return {}

        handler = object.__new__(handler_for(
            object(), expected_client_identity="spiffe://openkubes.io/ns/openkubes-console/sa/ok-console-bff",
        ))
        handler.path = "/api/console-observed-state/v0alpha2"
        handler.connection = Connection()
        responses = []
        handler.send_json = lambda status, body: responses.append((status, body))
        handler.do_GET()
        self.assertEqual(responses, [(403, {"error": "workload_identity_required"})])

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
