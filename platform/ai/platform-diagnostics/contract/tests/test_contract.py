"""Provider-neutral executable contract suite for ADR-Platform-021 tests 1-6."""

from __future__ import annotations

import json
import os
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import yaml
from jsonschema import Draft202012Validator, FormatChecker


TEST_DIR = Path(__file__).resolve().parent
DIAGNOSTICS_ROOT = TEST_DIR.parents[1]
DEFAULT_SPEC = DIAGNOSTICS_ROOT / "contract" / "openapi.yaml"
DEFAULT_RBAC = DIAGNOSTICS_ROOT / "profiles" / "stub" / "rbac.yaml"
STUB_ROOT = DIAGNOSTICS_ROOT / "profiles" / "stub"
sys.path.insert(0, str(STUB_ROOT))

from server import ProfileBHandler  # noqa: E402


REQUESTS = {
    "get_platform_health": {"clusters": ["contract-test"]},
    "investigate_workload": {
        "cluster": "contract-test",
        "namespace": "fixtures",
        "workload": "checkout-api",
        "time_range": "PT1H",
    },
    "collect_diagnostic_evidence": {
        "cluster": "contract-test",
        "namespace": "fixtures",
        "workload": "checkout-api",
        "time_range": "PT1H",
        "evidence_types": ["events", "logs", "host_journal"],
    },
}

PATHS = {
    "get_platform_health": "/v1/get_platform_health",
    "investigate_workload": "/v1/investigate_workload",
    "collect_diagnostic_evidence": "/v1/collect_diagnostic_evidence",
}


class ProviderClient:
    def __init__(self, base_url: str, bearer_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.bearer_token = bearer_token
        self.response_headers: dict[str, dict[str, str]] = {}

    def call(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            self.base_url + PATHS[operation],
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.bearer_token}",
                "Content-Type": "application/json",
                "X-Request-Id": f"contract-test-{operation}",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=10) as response:
                self.last_status = response.status
                self.response_headers[operation] = dict(response.headers.items())
                return json.loads(response.read())
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise AssertionError(
                f"{operation} returned HTTP {exc.code}: {body}"
            ) from exc

    def call_without_identity(
        self,
        operation: str,
        payload: dict[str, Any],
    ) -> tuple[int, dict[str, str], dict[str, Any]]:
        request = Request(
            self.base_url + PATHS[operation],
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=10) as response:
                raise AssertionError(
                    f"{operation} accepted a request without consumer identity "
                    f"with HTTP {response.status}"
                )
        except HTTPError as exc:
            return exc.code, dict(exc.headers.items()), json.loads(exc.read())


def _schema_validator(spec: dict[str, Any], schema: dict[str, Any]) -> Draft202012Validator:
    root = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "components": spec["components"],
        **schema,
    }
    Draft202012Validator.check_schema(root)
    return Draft202012Validator(root, format_checker=FormatChecker())


def _assert_schema(
    testcase: unittest.TestCase,
    spec: dict[str, Any],
    schema: dict[str, Any],
    instance: Any,
) -> None:
    errors = sorted(
        _schema_validator(spec, schema).iter_errors(instance),
        key=lambda error: list(error.absolute_path),
    )
    testcase.assertEqual(
        [],
        [f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}" for error in errors],
    )


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _assert_evidence_integrity(
    testcase: unittest.TestCase,
    response: dict[str, Any],
) -> None:
    evidence_ids = [item["id"] for item in response["evidence"]]
    testcase.assertEqual(
        len(evidence_ids),
        len(set(evidence_ids)),
        "EvidenceRef.id values must be unique within an invocation",
    )
    known_ids = set(evidence_ids)
    for hypothesis in response.get("probable_causes", []):
        testcase.assertLessEqual(set(hypothesis["evidence_refs"]), known_ids)
        testcase.assertLessEqual(
            set(hypothesis["contradicting_evidence_refs"]), known_ids
        )


class DiagnosticsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        spec_path = Path(os.getenv("OPENAPI_SPEC", DEFAULT_SPEC))
        cls.spec = yaml.safe_load(spec_path.read_text())
        cls.rbac_path = Path(os.getenv("DIAGNOSTICS_RBAC_PATH", DEFAULT_RBAC))
        bearer_token = os.getenv(
            "DIAGNOSTICS_BEARER_TOKEN", "profile-b-contract-test"
        )
        external_url = os.getenv("DIAGNOSTICS_BASE_URL")
        cls.httpd = None
        cls.thread = None
        if external_url:
            cls.client = ProviderClient(external_url, bearer_token)
        else:
            cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), ProfileBHandler)
            cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
            cls.thread.start()
            host, port = cls.httpd.server_address
            cls.client = ProviderClient(f"http://{host}:{port}", bearer_token)
        cls.responses = {
            operation: cls.client.call(operation, payload)
            for operation, payload in REQUESTS.items()
        }

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.httpd is not None:
            cls.httpd.shutdown()
            cls.httpd.server_close()
        if cls.thread is not None:
            cls.thread.join(timeout=5)

    def test_1_openapi_schema_conformance_and_provider_neutrality(self) -> None:
        expected_operations = set(PATHS)
        actual_operations = {
            item["post"]["operationId"]
            for item in self.spec["paths"].values()
        }
        self.assertEqual(expected_operations, actual_operations)
        self.assertEqual(set(PATHS.values()), set(self.spec["paths"]))
        self.assertEqual([{"bearerAuth": []}], self.spec["security"])

        public_surface = json.dumps(
            {
                "paths": self.spec["paths"],
                "components": self.spec["components"],
            }
        ).lower()
        for implementation_name in ("kagent", "openclaw", "ollama", "a2a"):
            self.assertNotIn(implementation_name, public_surface)

        for operation, payload in REQUESTS.items():
            post = self.spec["paths"][PATHS[operation]]["post"]
            request_schema = post["requestBody"]["content"]["application/json"]["schema"]
            response_schema = post["responses"]["200"]["content"]["application/json"]["schema"]
            _assert_schema(self, self.spec, request_schema, payload)
            _assert_schema(self, self.spec, response_schema, self.responses[operation])
            invocation_id = self.responses[operation]["invocation_id"]
            self.assertEqual(
                invocation_id,
                self.client.response_headers[operation]["X-Invocation-Id"],
            )

        status, headers, error = self.client.call_without_identity(
            "get_platform_health",
            REQUESTS["get_platform_health"],
        )
        self.assertEqual(401, status)
        unauthorized_schema = self.spec["components"]["responses"]["Unauthorized"][
            "content"
        ]["application/json"]["schema"]
        _assert_schema(self, self.spec, unauthorized_schema, error)
        self.assertEqual(error["invocation_id"], headers["X-Invocation-Id"])

        investigation = self.responses["investigate_workload"]
        evidence_bundle = self.responses["collect_diagnostic_evidence"]
        for response in (investigation, evidence_bundle):
            self.assertEqual("contract-test", response["cluster"])
            self.assertEqual("fixtures", response["namespace"])
            self.assertEqual("checkout-api", response["workload"])
            self.assertLessEqual(
                response["effective_time_range"]["start"],
                response["effective_time_range"]["end"],
            )

    def test_2_provider_rbac_is_read_only_and_secret_free(self) -> None:
        documents = [
            document
            for document in yaml.safe_load_all(self.rbac_path.read_text())
            if isinstance(document, dict)
        ]
        service_accounts = {
            (item["metadata"]["namespace"], item["metadata"]["name"])
            for item in documents
            if item.get("kind") == "ServiceAccount"
        }
        roles = {
            (item["kind"], item["metadata"]["name"]): item
            for item in documents
            if item.get("kind") in {"Role", "ClusterRole"}
        }
        bindings = [
            item for item in documents
            if item.get("kind") in {"RoleBinding", "ClusterRoleBinding"}
        ]
        self.assertTrue(service_accounts, "provider RBAC must declare its identity")
        self.assertTrue(roles, "provider RBAC must make its permission boundary explicit")
        self.assertTrue(bindings, "provider identity must bind to the audited role")

        allowed_verbs = {"get", "list", "watch"}
        for role in roles.values():
            for rule in role.get("rules", []):
                verbs = set(rule.get("verbs", []))
                resources = set(rule.get("resources", []))
                self.assertLessEqual(verbs, allowed_verbs)
                self.assertNotIn("*", resources)
                self.assertNotIn("secrets", resources)

        for binding in bindings:
            role_ref = binding["roleRef"]
            self.assertIn((role_ref["kind"], role_ref["name"]), roles)
            for subject in binding.get("subjects", []):
                if subject.get("kind") == "ServiceAccount":
                    namespace = subject.get("namespace", binding["metadata"].get("namespace"))
                    self.assertIn((namespace, subject["name"]), service_accounts)

    def test_3_evidence_is_reference_only_and_secret_free(self) -> None:
        evidence = (
            self.responses["investigate_workload"]["evidence"]
            + self.responses["collect_diagnostic_evidence"]["evidence"]
        )
        forbidden_exact_keys = {"raw", "content", "data"}
        forbidden_key_fragments = {"payload", "secret", "credential", "password", "token"}
        forbidden_fragments = ("begin private key", "bearer ", "password=", "token=")
        for item in evidence:
            self.assertTrue(item.get("id"))
            self.assertTrue(item.get("type"))
            self.assertTrue(item.get("source"))
            self.assertIn(item.get("status"), {"available", "unavailable", "partial"})
            if item["status"] in {"available", "partial"}:
                self.assertTrue(item.get("uri"), item)
                self.assertFalse(item["uri"].startswith("data:"), item)
            if item["status"] in {"unavailable", "partial"}:
                self.assertTrue(item.get("reason"), item)
            for node in _walk(item):
                for key in node:
                    lowered = key.lower()
                    self.assertNotIn(lowered, forbidden_exact_keys)
                    self.assertFalse(
                        any(fragment in lowered for fragment in forbidden_key_fragments),
                        key,
                    )

        serialized = json.dumps(
            {
                "investigation": self.responses["investigate_workload"],
                "evidence_bundle": self.responses["collect_diagnostic_evidence"],
            }
        ).lower()
        for fragment in forbidden_fragments:
            self.assertNotIn(fragment, serialized)

    def test_4_same_consumer_suite_runs_against_profile_b(self) -> None:
        self.assertEqual(200, self.client.last_status)
        self.assertEqual(
            set(PATHS),
            set(self.responses),
            "all public operations must run through the same HTTP client",
        )
        self.assertIsInstance(self.client, ProviderClient)

    def test_5_capability_delta_is_explicit(self) -> None:
        response = self.responses["collect_diagnostic_evidence"]
        capabilities = response["provider_capabilities"]
        self.assertIs(capabilities["host_journal"], False)
        journal = [item for item in response["evidence"] if item["type"] == "host_journal"]
        self.assertEqual(1, len(journal), "unsupported requested evidence was silently omitted")
        self.assertEqual("unavailable", journal[0]["status"])
        self.assertTrue(journal[0].get("reason"))

    def test_6_final_hypotheses_include_counter_evidence(self) -> None:
        response = self.responses["investigate_workload"]
        known_ids = {item["id"] for item in response["evidence"]}
        _assert_evidence_integrity(self, response)
        for hypothesis in response["probable_causes"]:
            self.assertTrue(hypothesis.get("confidence"))
            self.assertIn("contradicting_evidence_refs", hypothesis)
            self.assertIn(
                hypothesis.get("counter_evidence_status"),
                {"found", "none_found"},
            )
            self.assertTrue(hypothesis.get("evidence_refs"))
            self.assertLessEqual(set(hypothesis["evidence_refs"]), known_ids)
            self.assertLessEqual(
                set(hypothesis["contradicting_evidence_refs"]), known_ids
            )

        duplicate = json.loads(json.dumps(response))
        duplicate["evidence"][1]["id"] = duplicate["evidence"][0]["id"]
        with self.assertRaises(AssertionError):
            _assert_evidence_integrity(self, duplicate)

        dangling = json.loads(json.dumps(response))
        dangling["probable_causes"][0]["evidence_refs"] = ["ev-does-not-exist"]
        with self.assertRaises(AssertionError):
            _assert_evidence_integrity(self, dangling)


if __name__ == "__main__":
    unittest.main()
