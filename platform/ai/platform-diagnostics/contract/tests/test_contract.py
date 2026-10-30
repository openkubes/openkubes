"""Provider-neutral executable contract suite for ADR-Platform-021 tests 1-6.

The suite is parameterized over every provider in ``providers.registry()`` and
runs the identical assertions against each. Contract test 4 then compares the
providers against one another: a backend swap that is never performed cannot
prove that the contract is free of provider values, which is the only reason
Profile B exists.

``CONTRACT_VERSION`` pins the normative contract this suite was written against.
The pin is deliberate: resolving the contract relative to the checkout means a
branch that has fallen behind would otherwise validate happily against a stale
copy of the specification. That has happened, so it is a test, not advice.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

import providers


CONTRACT_VERSION = "1.1.0"

TEST_DIR = Path(__file__).resolve().parent
DIAGNOSTICS_ROOT = TEST_DIR.parents[1]
DEFAULT_SPEC = DIAGNOSTICS_ROOT / "contract" / "openapi.yaml"

# Volatile by design: correlation ids and timestamps differ on every call and on
# every provider. Everything else is contract surface and must be comparable.
VOLATILE_KEYS = frozenset(
    {"invocation_id", "generated_at", "collected_at", "effective_time_range"}
)

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
    """The consumer side of the contract. Identical for every provider."""

    def __init__(self, transport: providers.Transport, bearer_token: str) -> None:
        self.transport = transport
        self.bearer_token = bearer_token
        self.response_headers: dict[str, dict[str, str]] = {}
        self.last_status: int | None = None

    def _headers(self, operation: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.bearer_token}",
            "Content-Type": "application/json",
            "X-Request-Id": f"contract-test-{operation}",
        }

    def call(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        status, headers, body = self.transport.send(
            PATHS[operation], payload, self._headers(operation)
        )
        self.last_status = status
        self.response_headers[operation] = {
            key.title(): value for key, value in headers.items()
        }
        if status != 200:
            raise AssertionError(
                f"{operation} returned HTTP {status}: "
                f"{body.decode('utf-8', errors='replace')}"
            )
        return json.loads(body)

    def call_without_identity(
        self,
        operation: str,
        payload: dict[str, Any],
    ) -> tuple[int, dict[str, str], dict[str, Any]]:
        status, headers, body = self.transport.send(
            PATHS[operation], payload, {"Content-Type": "application/json"}
        )
        if status == 200:
            raise AssertionError(
                f"{operation} accepted a request without consumer identity"
            )
        return (
            status,
            {key.title(): value for key, value in headers.items()},
            json.loads(body),
        )


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


def _response_schema(spec: dict[str, Any], operation: str) -> dict[str, Any]:
    return spec["paths"][PATHS[operation]]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _without_volatile(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_volatile(child)
            for key, child in value.items()
            if key not in VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [_without_volatile(child) for child in value]
    return value


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


# Synthetic input for the negative half of test 6. Provider-independent on
# purpose: it exercises the integrity checker, not a provider.
_INTEGRITY_PROBE = {
    "evidence": [
        {"id": "ev-one", "type": "events", "source": "probe", "status": "unavailable",
         "reason": "probe", "collected_at": "2026-08-14T10:00:00Z"},
        {"id": "ev-two", "type": "logs", "source": "probe", "status": "unavailable",
         "reason": "probe", "collected_at": "2026-08-14T10:00:00Z"},
    ],
    "probable_causes": [
        {
            "hypothesis": "probe",
            "confidence": "low",
            "evidence_refs": ["ev-one"],
            "contradicting_evidence_refs": ["ev-two"],
            "counter_evidence_status": "found",
        }
    ],
}


def load_spec() -> dict[str, Any]:
    spec_path = Path(os.getenv("OPENAPI_SPEC", DEFAULT_SPEC))
    return yaml.safe_load(spec_path.read_text())


def exercise(provider: providers.Provider) -> tuple[ProviderClient, dict[str, Any]]:
    """Run the identical request set through one provider."""
    transport = provider.start()
    client = ProviderClient(transport, providers.BEARER_TOKEN)
    responses = {
        operation: client.call(operation, payload)
        for operation, payload in REQUESTS.items()
    }
    return client, responses


class ContractInvariants:
    """ADR-021 tests 1, 2, 3, 5 and 6 for a single provider.

    Not a TestCase, so it is not collected on its own: ``load_tests`` builds one
    concrete TestCase per registered provider from it. That guarantees every
    provider is held to the same assertions rather than to a variant of them.
    """

    provider: providers.Provider

    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = load_spec()
        cls.client, cls.responses = exercise(cls.provider)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.transport.close()

    def test_1_openapi_schema_conformance_and_provider_neutrality(self) -> None:
        self.assertEqual(
            CONTRACT_VERSION,
            self.spec["info"]["version"],
            "the suite is pinned to a normative contract version; a differing "
            "specification must be adopted deliberately, not resolved by "
            "checkout layout",
        )

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
            _assert_schema(self, self.spec, request_schema, payload)
            _assert_schema(
                self, self.spec, _response_schema(self.spec, operation),
                self.responses[operation],
            )
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
            for document in yaml.safe_load_all(self.provider.rbac_path.read_text())
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

        # The integrity checker itself is verified against synthetic input rather
        # than against a mutated provider response: how many evidence items a
        # provider happens to return is a provider property, and a negative test
        # that silently degrades to a no-op on a thin response proves nothing.
        duplicate = json.loads(json.dumps(_INTEGRITY_PROBE))
        duplicate["evidence"][1]["id"] = duplicate["evidence"][0]["id"]
        with self.assertRaises(AssertionError):
            _assert_evidence_integrity(self, duplicate)

        dangling = json.loads(json.dumps(_INTEGRITY_PROBE))
        dangling["probable_causes"][0]["evidence_refs"] = ["ev-does-not-exist"]
        with self.assertRaises(AssertionError):
            _assert_evidence_integrity(self, dangling)

        # Sanity: unmutated, the probe must pass, otherwise the two checks above
        # could be passing for the wrong reason.
        _assert_evidence_integrity(self, json.loads(json.dumps(_INTEGRITY_PROBE)))


class BackendSwapTests(unittest.TestCase):
    """ADR-021 test 4.

    Runs the same consumer suite against every registered provider inside one
    run and compares the results. Two things have to hold: each provider answers
    the identical requests conformantly, and the answers are demonstrably not the
    same artifact. The second half is what a single-provider run cannot show.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = load_spec()
        cls.registry = providers.registry()
        cls.clients: dict[str, ProviderClient] = {}
        cls.results: dict[str, dict[str, Any]] = {}
        for provider in cls.registry:
            client, responses = exercise(provider)
            cls.clients[provider.key] = client
            cls.results[provider.key] = responses

    @classmethod
    def tearDownClass(cls) -> None:
        for client in cls.clients.values():
            client.transport.close()

    def test_4_backend_swap_runs_the_same_suite_against_every_provider(self) -> None:
        self.assertGreaterEqual(
            len(self.results),
            2,
            "the backend-swap test needs at least two independent providers; "
            "with one provider it cannot detect a provider value that leaked "
            "into the contract",
        )

        for key, responses in self.results.items():
            with self.subTest(provider=key):
                self.assertEqual(set(REQUESTS), set(responses))
                self.assertEqual(200, self.clients[key].last_status)
                for operation in REQUESTS:
                    _assert_schema(
                        self,
                        self.spec,
                        _response_schema(self.spec, operation),
                        responses[operation],
                    )

        invocation_ids = [
            response["invocation_id"]
            for responses in self.results.values()
            for response in responses.values()
        ]
        self.assertEqual(
            len(invocation_ids),
            len(set(invocation_ids)),
            "every invocation must be individually identifiable in the audit trail",
        )

        keys = sorted(self.results)
        for left, right in zip(keys, keys[1:]):
            differing = [
                operation
                for operation in REQUESTS
                if _without_volatile(self.results[left][operation])
                != _without_volatile(self.results[right][operation])
            ]
            self.assertTrue(
                differing,
                f"{left} and {right} returned identical payloads for every "
                "operation, so the suite did not actually swap the backend",
            )


def load_tests(loader, tests, pattern):  # noqa: ARG001 - unittest protocol
    suite = unittest.TestSuite()
    for provider in providers.registry():
        case = type(
            f"ContractTests_{provider.key.replace('-', '_')}",
            (ContractInvariants, unittest.TestCase),
            {"provider": provider, "__doc__": provider.description},
        )
        suite.addTests(loader.loadTestsFromTestCase(case))
    suite.addTests(loader.loadTestsFromTestCase(BackendSwapTests))
    return suite


if __name__ == "__main__":
    unittest.main()
