import json
import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker


os.environ.setdefault("DIAGNOSTICS_BEARER_TOKEN", "profile-a-contract-test")

from app import (
    AgentError,
    Confidence,
    CounterEvidence,
    EvidenceRef,
    EvidenceStatus,
    RankedHypothesis,
    _event_matches_workload,
    _extract_json,
    _grounded_hypotheses,
    _investigation_validation_errors,
    app,
)


ACTUAL_URI = (
    "k8s://ok-ai/namespaces/ok14-evidence/pods/"
    "uc1-crashloop-6d9c8b7f5c-x2abc/logs?container=app"
)
ACTUAL_ID = "ev-canonical-pod-log"
FACADE_DIR = Path(__file__).resolve().parents[1]
SPEC_PATH = FACADE_DIR.parents[2] / "contract" / "openapi.yaml"
SPEC = yaml.safe_load(SPEC_PATH.read_text())


def hypothesis(confidence: Confidence, ref: str = ACTUAL_ID) -> RankedHypothesis:
    return RankedHypothesis(
        hypothesis="Startup failed because the required DB_DSN key is missing.",
        confidence=confidence,
        evidence_refs=[ref],
        counter_evidence_status=CounterEvidence.none_found,
    )


class InvestigationValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.canonical = [
            EvidenceRef(
                id=ACTUAL_ID,
                type="pod_logs",
                source="k8s_get_pod_logs",
                status=EvidenceStatus.available,
                uri=ACTUAL_URI,
            )
        ]

    def test_accepts_ranked_causes_with_canonical_references(self) -> None:
        errors = _investigation_validation_errors(
            ["Container exits during startup."],
            self.canonical,
            [
                hypothesis(Confidence.high),
                hypothesis(Confidence.medium),
            ],
            self.canonical,
        )
        self.assertEqual([], errors)

    def test_rejects_fabricated_evidence_and_unranked_causes(self) -> None:
        fabricated_uri = (
            "k8s://ok-ai/namespaces/ok14-evidence/pods/"
            "uc1-crashloop-abcde/logs?container=app"
        )
        errors = _investigation_validation_errors(
            ["Container exits during startup."],
            self.canonical,
            [
                hypothesis(Confidence.medium),
                hypothesis(Confidence.high),
            ],
            [
                EvidenceRef(
                    type="pod_logs",
                    source="agent",
                    status=EvidenceStatus.available,
                    uri=fabricated_uri,
                )
            ],
        )
        self.assertIn(
            "agent returned evidence outside the collected catalog",
            errors,
        )
        self.assertIn(
            "probable causes are not ranked by descending confidence",
            errors,
        )

    def test_rejects_hypothesis_reference_outside_catalog(self) -> None:
        errors = _investigation_validation_errors(
            ["Container exits during startup."],
            self.canonical,
            [
                hypothesis(
                    Confidence.high,
                    "ev-fabricated",
                )
            ],
        )
        self.assertTrue(any(
            error.startswith("hypothesis 1 references unknown evidence:")
            for error in errors
        ))

    def test_drops_ungrounded_secondary_cause_and_keeps_valid_top_cause(self) -> None:
        grounded = _grounded_hypotheses(
            self.canonical,
            [
                hypothesis(Confidence.high, ACTUAL_URI),
                RankedHypothesis(
                    hypothesis="Unsupported secondary guess.",
                    confidence=Confidence.low,
                    evidence_refs=[],
                    counter_evidence_status=CounterEvidence.none_found,
                ),
            ],
        )
        self.assertEqual(1, len(grounded))
        self.assertIn("DB_DSN", grounded[0].hypothesis)
        self.assertEqual([ACTUAL_ID], grounded[0].evidence_refs)

    def test_accepts_reference_to_unavailable_evidence_by_stable_id(self) -> None:
        unavailable = EvidenceRef(
            id="ev-host-journal-unavailable",
            type="host_journal",
            source="kagent",
            status=EvidenceStatus.unavailable,
            reason="collector is not available on Talos",
        )
        grounded = _grounded_hypotheses(
            self.canonical + [unavailable],
            [
                RankedHypothesis(
                    hypothesis="Host-level evidence could not be checked.",
                    confidence=Confidence.low,
                    evidence_refs=[unavailable.id],
                    counter_evidence_status=CounterEvidence.none_found,
                )
            ],
        )
        self.assertEqual([unavailable.id], grounded[0].evidence_refs)


class AgentJsonTests(unittest.TestCase):
    def test_extracts_nested_json_from_markdown_fence(self) -> None:
        text = (
            "```json\n"
            '{"summary":"grounded","evidence":[{"type":"logs","uri":"k8s://pod"}]}'
            "\n```"
        )
        self.assertEqual(
            "k8s://pod",
            _extract_json(text)["evidence"][0]["uri"],
        )


class WorkloadIdentityTests(unittest.TestCase):
    def test_matches_only_actual_workload_event_identity(self) -> None:
        pod_names = {"uc1-crashloop-6d9c8b7f5c-x2abc"}
        self.assertTrue(_event_matches_workload(
            {"involvedObject": {"name": "uc1-crashloop-6d9c8b7f5c-x2abc"}},
            "uc1-crashloop",
            pod_names,
        ))
        self.assertFalse(_event_matches_workload(
            {"involvedObject": {"name": "unrelated-workload-abcde"}},
            "uc1-crashloop",
            pod_names,
        ))


def assert_contract_response(
    testcase: unittest.TestCase,
    path: str,
    payload: dict,
) -> None:
    response_schema = SPEC["paths"][path]["post"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "components": SPEC["components"],
        **response_schema,
    }
    errors = list(
        Draft202012Validator(
            schema, format_checker=FormatChecker()
        ).iter_errors(payload)
    )
    testcase.assertEqual([], [error.message for error in errors])


class HttpContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.headers = {
            "Authorization": "Bearer profile-a-contract-test",
            "X-Request-Id": "profile-a-test-request",
        }

    def assert_correlated(self, response) -> dict:
        payload = response.json()
        self.assertTrue(response.headers["X-Invocation-Id"])
        self.assertEqual(
            response.headers["X-Invocation-Id"], payload["invocation_id"]
        )
        return payload

    def test_consumer_identity_is_required_and_error_is_correlated(self) -> None:
        response = self.client.post("/v1/get_platform_health", json={})
        self.assertEqual(401, response.status_code)
        payload = response.json()
        self.assertEqual("unauthorized", payload["code"])
        self.assertEqual(
            response.headers["X-Invocation-Id"], payload["invocation_id"]
        )

    def test_health_maps_ambiguous_provider_state_to_unknown(self) -> None:
        agent_reply = json.dumps(
            {
                "clusters": [
                    {
                        "cluster": "ok-ai",
                        "status": "ambiguous",
                        "summary": "provider signal was inconclusive",
                        "signals": [],
                    }
                ]
            }
        )
        with patch("app.invoke_agent", AsyncMock(return_value=agent_reply)):
            response = self.client.post(
                "/v1/get_platform_health",
                headers=self.headers,
                json={"clusters": ["ok-ai"]},
            )
        self.assertEqual(200, response.status_code, response.text)
        payload = self.assert_correlated(response)
        self.assertEqual("unknown", payload["clusters"][0]["status"])
        assert_contract_response(self, "/v1/get_platform_health", payload)

    def test_inventory_investigation_is_self_describing_and_conformant(self) -> None:
        with patch("app._get_workload_pods", AsyncMock(return_value=[])):
            response = self.client.post(
                "/v1/investigate_workload",
                headers=self.headers,
                json={
                    "cluster": "ok-ai",
                    "namespace": "payments",
                    "workload": "checkout-api",
                    "time_range": "PT1H",
                },
            )
        self.assertEqual(200, response.status_code, response.text)
        payload = self.assert_correlated(response)
        self.assertEqual("payments", payload["namespace"])
        self.assertTrue(payload["evidence"][0]["id"])
        assert_contract_response(self, "/v1/investigate_workload", payload)

    def test_investigation_provider_failure_is_a_correlated_503(self) -> None:
        with patch(
            "app._get_workload_pods",
            AsyncMock(side_effect=AgentError("private provider detail")),
        ):
            response = self.client.post(
                "/v1/investigate_workload",
                headers=self.headers,
                json={
                    "cluster": "ok-ai",
                    "namespace": "payments",
                    "workload": "checkout-api",
                },
            )
        self.assertEqual(503, response.status_code)
        payload = response.json()
        self.assertEqual("provider_unavailable", payload["code"])
        self.assertNotIn("private provider detail", payload["message"])
        self.assertEqual(
            response.headers["X-Invocation-Id"], payload["invocation_id"]
        )
        error_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "components": SPEC["components"],
            "$ref": "#/components/schemas/Error",
        }
        errors = list(Draft202012Validator(error_schema).iter_errors(payload))
        self.assertEqual([], [error.message for error in errors])

    def test_evidence_bundle_is_self_describing_and_conformant(self) -> None:
        collected = EvidenceRef(
            id="ev-events",
            type="events",
            source="k8s_get_events",
            status=EvidenceStatus.available,
            reason="matched_events=0",
            uri="k8s://ok-ai/namespaces/payments/workloads/checkout-api/events",
        )
        with (
            patch("app._get_workload_pods", AsyncMock(return_value=[])),
            patch(
                "app._collect_workload_observations",
                AsyncMock(return_value=({}, [collected])),
            ),
        ):
            response = self.client.post(
                "/v1/collect_diagnostic_evidence",
                headers=self.headers,
                json={
                    "cluster": "ok-ai",
                    "namespace": "payments",
                    "workload": "checkout-api",
                    "time_range": "PT1H",
                    "evidence_types": ["events", "host_journal"],
                },
            )
        self.assertEqual(200, response.status_code, response.text)
        payload = self.assert_correlated(response)
        ids = [item["id"] for item in payload["evidence"]]
        self.assertEqual(len(ids), len(set(ids)))
        unavailable = next(
            item for item in payload["evidence"] if item["type"] == "host_journal"
        )
        self.assertEqual("unavailable", unavailable["status"])
        self.assertNotIn("uri", unavailable)
        assert_contract_response(
            self, "/v1/collect_diagnostic_evidence", payload
        )


class ChartContractTests(unittest.TestCase):
    def test_chart_requires_consumer_secret_and_disables_kube_token(self) -> None:
        chart_dir = FACADE_DIR.parent / "charts" / "platform-diagnostics-facade"
        values = yaml.safe_load((chart_dir / "values.yaml").read_text())
        chart = yaml.safe_load((chart_dir / "Chart.yaml").read_text())
        deployment = (chart_dir / "templates" / "deployment.yaml").read_text()

        self.assertEqual("0.2.0", chart["version"])
        self.assertEqual("1.1.0", chart["appVersion"])
        self.assertEqual("0.1.8", values["image"]["tag"])
        self.assertEqual(
            "platform-diagnostics-mcp-consumer",
            values["consumerAuth"]["secretName"],
        )
        self.assertIn("automountServiceAccountToken: false", deployment)
        self.assertIn("DIAGNOSTICS_BEARER_TOKEN", deployment)
        self.assertIn(".Values.consumerAuth.secretName", deployment)
        self.assertNotIn("serviceAccountName:", deployment)


if __name__ == "__main__":
    unittest.main()
