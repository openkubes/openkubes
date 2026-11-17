import copy
import hashlib
import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from app import (
    QUERY_PATH,
    QUERY_VERSION,
    QUERY_V2_PATH,
    QUERY_V2_VERSION,
    OwnershipError,
    ObservedStateProducer,
    ProducerConfig,
    build_hosting_cluster_state,
    build_observed_state,
    handler_for,
    ownership_projection,
)
from test_app import NOW, claim, claim_list, hosting_observation


def canonical_sha256(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def wire_sha256(payload):
    encoded = json.dumps(payload, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def tenant_map(directory, entries):
    path = Path(directory) / "ownership.json"
    path.write_text(json.dumps({"tenants": entries}), encoding="utf-8")
    return str(path)


def claims_client(*items):
    class Client:
        def list_cluster_claims(self, _namespace):
            return claim_list(*items)

    return Client()


class OwnershipProjectionTests(unittest.TestCase):
    def test_v1_claims_and_hosting_serialization_remain_unchanged(self):
        claims = build_observed_state(claim_list(claim()), ProducerConfig(), now=lambda: NOW, read_started_at="2026-08-21T18:30:00Z")
        hosting = build_hosting_cluster_state(
            hosting_observation(),
            ProducerConfig(source_mode="hosting-cluster"),
            now=lambda: NOW,
            read_started_at="2026-08-21T18:30:00Z", workload_read_times={"ok-console": "2026-08-21T18:30:00Z"},
        )

        # Claim hashes include read time instead of the Ready transition time.
        self.assertEqual(canonical_sha256(claims), "c84b517f0dd2695effae2ab15ff2be3b430145e9cb47ba034561c78d54744abf")
        self.assertEqual(canonical_sha256(hosting), "782c5865ea36a41d79b7a2177a8281c05bd406390933f62ca70e1e4ce64b4a70")
        self.assertEqual(wire_sha256(claims), "5fd9d824825a5098a3f1cce5c19598fa163e9e7d763e150901498110b75f1de8")
        self.assertEqual(wire_sha256(hosting), "b92ffbcc179f0d00c984731d13560adc1ac175289b93e1459184c1fdb8db0761")

    def test_assigns_mixed_tenants_by_source_keys_and_ignores_forged_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            source_alpha = claim("alpha")
            source_alpha["metadata"]["labels"] = {"tenant": "forged-label"}
            tenants = {
                "management/ok-mgmt": "platform",
                "claim/openkubes-system/alpha": "team-a",
                "claim/openkubes-system/beta": "team-b",
            }
            config = ProducerConfig(ownership_file=tenant_map(directory, tenants))
            payload = build_observed_state(
                claim_list(source_alpha, claim("beta")), config, now=lambda: NOW,
                read_started_at="2026-08-21T18:30:00Z",
            )

            projected = ownership_projection(payload, config, tenants)

        clusters = {item["name"]: item for item in projected["data"]["clusters"]}
        self.assertEqual(clusters["ok-mgmt"]["ownership"], {"environmentId": config.environment_id, "tenantId": "platform"})
        self.assertEqual(clusters["alpha"]["ownership"], {"environmentId": config.environment_id, "tenantId": "team-a"})
        self.assertEqual(clusters["beta"]["ownership"], {"environmentId": config.environment_id, "tenantId": "team-b"})
        evidence = {item["id"]: item for item in projected["data"]["evidence"]}
        self.assertEqual(evidence["ev-alpha-claim-readiness"]["ownership"]["tenantId"], "team-a")
        self.assertEqual(evidence["ev-beta-claim-readiness"]["ownership"]["tenantId"], "team-b")

    def test_hosting_owner_and_evidence_owner_follow_cluster_id(self):
        with tempfile.TemporaryDirectory() as directory:
            tenants = {
                "management/ok-mgmt": "platform",
                "hosting/ok-shared": "shared-services",
            }
            config = ProducerConfig(
                source_mode="hosting-cluster",
                ownership_file=tenant_map(directory, tenants),
            )
            payload = build_hosting_cluster_state(hosting_observation(), config, now=lambda: NOW, read_started_at="2026-08-21T18:30:00Z", workload_read_times={"ok-console": "2026-08-21T18:30:00Z"})
            # Display fields are presentation only and cannot alter the id-to-owner relation.
            payload["data"]["clusters"][1]["name"] = "display-name-is-not-authority"
            payload["data"]["evidence"][1]["title"] = "forged title"

            projected = ownership_projection(payload, config, tenants)

        hosting = projected["data"]["clusters"][1]
        evidence = projected["data"]["evidence"][1]
        self.assertEqual(hosting["id"], "cluster-ok-shared")
        self.assertEqual(hosting["ownership"]["tenantId"], "shared-services")
        self.assertEqual(evidence["clusterId"], "cluster-ok-shared")
        self.assertEqual(evidence["ownership"]["tenantId"], "shared-services")

    def test_capabilities_inherit_parent_tenant_and_placements_use_target_cluster_id(self):
        config = ProducerConfig()
        payload = {
            "data": {
                "clusters": [
                    {"id": "cluster-ok-mgmt", "name": "ok-mgmt", "capabilities": []},
                    {
                        "id": "cluster-alpha",
                        "name": "alpha",
                        "ownership": {"environmentId": "forged", "tenantId": "forged-cluster-tenant"},
                        "capabilities": [
                            {"id": "cap-storage", "ownership": {"environmentId": "forged", "tenantId": "forged-capability-tenant"}}
                        ],
                    },
                    {"id": "cluster-beta", "name": "beta", "capabilities": []},
                ],
                "placements": [
                    {
                        "id": "placement-alpha",
                        "targetClusterId": "cluster-alpha",
                        "targetCluster": "beta",
                        "ownership": {"environmentId": "forged", "tenantId": "forged-placement-tenant"},
                    }
                ],
                "evidence": [],
                "metrics": {
                    "capabilities": {"total": 0, "ready": 0, "pending": 0, "failed": 0, "unknown": 0},
                    "workloadClaims": {"total": 0, "ready": 0, "pending": 0, "failed": 0, "unknown": 0},
                    "openFindings": {"total": 0, "critical": 0},
                },
            }
        }

        projected = ownership_projection(
            payload,
            config,
            {"management/ok-mgmt": "platform", "claim/openkubes-system/alpha": "team-a", "claim/openkubes-system/beta": "team-b"},
        )

        cluster = projected["data"]["clusters"][1]
        expected_owner = {"environmentId": config.environment_id, "tenantId": "team-a"}
        self.assertEqual(cluster["ownership"], expected_owner)
        self.assertEqual(cluster["capabilities"][0]["ownership"], expected_owner)
        self.assertEqual(projected["data"]["placements"][0]["ownership"], expected_owner)
        self.assertNotIn("forged", json.dumps(projected))

    def test_metrics_are_partial_per_tenant_and_keep_zero_values(self):
        payload = {
            "data": {
                "clusters": [
                    {"id": "cluster-ok-mgmt", "name": "ok-mgmt", "capabilities": []},
                    {"id": "cluster-alpha", "name": "alpha", "capabilities": []},
                    {"id": "cluster-beta", "name": "beta", "capabilities": []},
                ],
                "placements": [],
                "evidence": [],
                "metrics": {
                    "capabilities": {"total": 0, "ready": 0, "pending": 0, "failed": 0, "unknown": 0},
                    "workloadClaims": {"total": 0, "ready": 0, "pending": 0, "failed": 0, "unknown": 0},
                    "openFindings": {"total": None, "critical": None},
                },
            }
        }

        projected = ownership_projection(
            payload,
            ProducerConfig(),
            {"management/ok-mgmt": "platform", "claim/openkubes-system/alpha": "team-a", "claim/openkubes-system/beta": "team-a"},
        )

        buckets = projected["data"]["metrics"]
        self.assertEqual([bucket["ownership"]["tenantId"] for bucket in buckets], ["platform", "team-a"])
        self.assertEqual(len(buckets), 2)
        for bucket in buckets:
            self.assertEqual(bucket["capabilities"], payload["data"]["metrics"]["capabilities"])
            self.assertEqual(bucket["workloadClaims"], payload["data"]["metrics"]["workloadClaims"])
            self.assertEqual(bucket["openFindings"], payload["data"]["metrics"]["openFindings"])
            self.assertIsNot(bucket["capabilities"], payload["data"]["metrics"]["capabilities"])

    def test_nonzero_global_metrics_cannot_be_attributed_and_fail_closed(self):
        # A global count copied into every tenant bucket would show each tenant everyone's total.
        payload = {
            "data": {
                "clusters": [
                    {"id": "cluster-ok-mgmt", "name": "ok-mgmt", "capabilities": []},
                    {"id": "cluster-alpha", "name": "alpha", "capabilities": []},
                ],
                "placements": [],
                "evidence": [],
                "metrics": {
                    "capabilities": {"total": 0, "ready": 0, "pending": 0, "failed": 0, "unknown": 0},
                    "workloadClaims": {"total": 3, "ready": 3, "pending": 0, "failed": 0, "unknown": 0},
                    "openFindings": {"total": 0, "critical": 0},
                },
            }
        }

        with self.assertRaises(OwnershipError) as raised:
            ownership_projection(
                payload,
                ProducerConfig(),
                {"management/ok-mgmt": "platform", "claim/openkubes-system/alpha": "team-a"},
            )
        self.assertEqual(raised.exception.object_key, "metrics/workloadClaims")

    def test_projection_does_not_mutate_input(self):
        payload = {
            "data": {
                "clusters": [
                    {"id": "cluster-ok-mgmt", "name": "ok-mgmt", "capabilities": []},
                    {"id": "cluster-alpha", "name": "alpha", "capabilities": []},
                ],
                "placements": [],
                "evidence": [],
                "metrics": {},
            }
        }
        original = copy.deepcopy(payload)

        ownership_projection(
            payload, ProducerConfig(),
            {"management/ok-mgmt": "platform", "claim/openkubes-system/alpha": "team-a"},
        )

        self.assertEqual(payload, original)

    def test_allocation_failure_key_is_bounded_and_single_line(self):
        error = OwnershipError("claim/" + ("x" * 300) + "\nprivate")

        self.assertLessEqual(len(error.object_key), 256)
        self.assertNotIn("\n", error.object_key)
        self.assertNotIn("private", error.object_key)


class OwnershipConfigurationTests(unittest.TestCase):
    def test_missing_malformed_oversize_and_unreadable_files_make_v2_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = str(Path(directory) / "missing.json")
            malformed = Path(directory) / "malformed.json"
            malformed.write_text("{not-json", encoding="utf-8")
            oversize = Path(directory) / "oversize.json"
            oversize.write_text(" " * (64 * 1024 + 1), encoding="utf-8")
            config_for = lambda path: ProducerConfig(ownership_file=str(path))

            for path in (missing, str(malformed), str(oversize)):
                with self.subTest(path=path):
                    producer = ObservedStateProducer(claims_client(claim()), config_for(path), now=lambda: NOW)
                    with self.assertRaises(ValueError):
                        producer.snapshot_v2()
                    self.assertEqual(producer.snapshot()["kind"], "ConsoleObservedState")

            secret_file = Path(directory) / "secret.json"
            secret_file.write_text("{\"tenants\":{}}", encoding="utf-8")
            with patch("app.Path.open", side_effect=PermissionError("denied")) as open_file:
                unreadable = ObservedStateProducer(
                    claims_client(claim()), config_for(secret_file), now=lambda: NOW
                )
            open_file.assert_called_once()
            with self.assertRaises(ValueError):
                unreadable.snapshot_v2()
            self.assertEqual(unreadable.snapshot()["kind"], "ConsoleObservedState")

    def test_ownership_file_can_be_selected_by_server_environment(self):
        config = ProducerConfig.from_environment(
            {"OK_OBSERVER_OWNERSHIP_FILE": "/var/run/openkubes/ownership.json"}
        )

        self.assertEqual(config.ownership_file, "/var/run/openkubes/ownership.json")

    def test_rejects_invalid_tenant_values_including_whitespace(self):
        for invalid in ("", " ", "\t", "\nteam", "team\n", "x" * 257, 17, None):
            with self.subTest(tenant=repr(invalid)), tempfile.TemporaryDirectory() as directory:
                path = tenant_map(directory, {"management/ok-mgmt": "platform", "claim/openkubes-system/alpha": invalid})
                producer = ObservedStateProducer(
                    claims_client(claim("alpha")), ProducerConfig(ownership_file=path), now=lambda: NOW
                )
                with self.assertRaises(ValueError):
                    producer.snapshot_v2()

    def test_startup_load_is_immutable_until_a_new_producer_is_constructed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = tenant_map(directory, {"management/ok-mgmt": "platform", "claim/openkubes-system/alpha": "team-a"})
            config = ProducerConfig(ownership_file=path)
            producer = ObservedStateProducer(claims_client(claim("alpha")), config, now=lambda: NOW)
            Path(path).write_text(json.dumps({"tenants": {"management/ok-mgmt": "platform", "claim/openkubes-system/alpha": "team-b"}}), encoding="utf-8")

            first = producer.snapshot_v2()
            restarted = ObservedStateProducer(claims_client(claim("alpha")), config, now=lambda: NOW).snapshot_v2()

        self.assertEqual(first["data"]["clusters"][1]["ownership"]["tenantId"], "team-a")
        self.assertEqual(restarted["data"]["clusters"][1]["ownership"]["tenantId"], "team-b")

    def test_unmapped_claim_disables_v2_but_keeps_v1_available(self):
        with tempfile.TemporaryDirectory() as directory:
            path = tenant_map(directory, {"management/ok-mgmt": "platform", "claim/openkubes-system/other": "team-a"})
            producer = ObservedStateProducer(
                claims_client(claim("alpha")), ProducerConfig(ownership_file=path), now=lambda: NOW
            )

            with self.assertRaises(ValueError) as raised:
                producer.snapshot_v2()
            self.assertEqual(raised.exception.object_key, "claim/openkubes-system/alpha")
            self.assertEqual(producer.snapshot()["kind"], "ConsoleObservedState")


class OwnershipHttpTests(unittest.TestCase):
    def test_serves_v2_and_returns_generic_bounded_allocation_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = tenant_map(directory, {"management/ok-mgmt": "platform", "claim/openkubes-system/alpha": "team-a"})
            producer = ObservedStateProducer(
                claims_client(claim("alpha")), ProducerConfig(ownership_file=path), now=lambda: NOW
            )
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0), handler_for(producer, require_client_identity=False)
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                response, body = self.request(server, QUERY_V2_PATH)
                self.assertEqual(response.status, 200)
                self.assertEqual(body["apiVersion"], QUERY_V2_VERSION)
                self.assertEqual(
                    response.getheader("Content-Type"),
                    f'application/json; profile="{QUERY_V2_VERSION}"',
                )
                self.assertEqual(body["data"]["clusters"][1]["ownership"]["tenantId"], "team-a")

                # A source object added without a startup tenant assignment cannot leak through v2.
                producer.client = claims_client(claim("alpha"), claim("unmapped"))
                with patch("app.print", create=True) as app_print:
                    unavailable, error = self.request(server, QUERY_V2_PATH)
                self.assertEqual(unavailable.status, 503)
                self.assertEqual(error, {"error": "source_unavailable", "retryable": True})
                ownership_lines = [
                    call.args[0] for call in app_print.call_args_list
                    if call.args and str(call.args[0]).startswith("observed-state-producer ownership unavailable ")
                ]
                self.assertEqual(
                    ownership_lines,
                    ["observed-state-producer ownership unavailable key=claim/openkubes-system/unmapped"],
                )
                self.assertNotIn("private", ownership_lines[0])

                legacy, legacy_body = self.request(server, QUERY_PATH)
                self.assertEqual(legacy.status, 200)
                self.assertEqual(legacy_body["apiVersion"], QUERY_VERSION)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_bad_ownership_files_return_generic_v2_503_and_preserve_v1(self):
        with tempfile.TemporaryDirectory() as directory:
            malformed = Path(directory) / "malformed.json"
            malformed.write_text("PRIVATE-MAP-CONTENT-{", encoding="utf-8")
            nonstring = Path(directory) / "nonstring.json"
            nonstring.write_text(
                json.dumps({"tenants": {"management/ok-mgmt": 7}}), encoding="utf-8"
            )
            empty = Path(directory) / "empty.json"
            empty.write_text(json.dumps({"tenants": {}}), encoding="utf-8")
            cases = [
                ("missing", ProducerConfig(ownership_file=str(Path(directory) / "missing.json"))),
                ("malformed", ProducerConfig(ownership_file=str(malformed))),
                ("nonstring", ProducerConfig(ownership_file=str(nonstring))),
                ("empty", ProducerConfig(ownership_file=str(empty))),
            ]

            for name, config in cases:
                with self.subTest(name=name):
                    producer = ObservedStateProducer(
                        claims_client(claim("alpha")), config, now=lambda: NOW
                    )
                    self.assert_http_v2_unavailable_and_v1_available(producer)

            unreadable_path = Path(directory) / "unreadable.json"
            unreadable_path.write_text("{\"tenants\":{}}", encoding="utf-8")
            unreadable_config = ProducerConfig(ownership_file=str(unreadable_path))
            with patch("app.Path.open", side_effect=PermissionError("PRIVATE-READ-FAILURE")) as open_file:
                unreadable = ObservedStateProducer(
                    claims_client(claim("alpha")), unreadable_config, now=lambda: NOW
                )
            open_file.assert_called_once()
            self.assert_http_v2_unavailable_and_v1_available(unreadable)

    def assert_http_v2_unavailable_and_v1_available(self, producer):
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), handler_for(producer, require_client_identity=False)
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            v2, body = self.request(server, QUERY_V2_PATH)
            self.assertEqual(v2.status, 503)
            self.assertEqual(body, {"error": "source_unavailable", "retryable": True})
            self.assertEqual(
                v2.getheader("Content-Type"),
                f'application/json; profile="{QUERY_V2_VERSION}"',
            )

            v1, legacy_body = self.request(server, QUERY_PATH)
            self.assertEqual(v1.status, 200)
            self.assertEqual(legacy_body["apiVersion"], QUERY_VERSION)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    @staticmethod
    def request(server, path):
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        connection.request("GET", path)
        response = connection.getresponse()
        body = json.loads(response.read())
        connection.close()
        return response, body


if __name__ == "__main__":
    unittest.main()
