import unittest

from app import (
    Confidence,
    CounterEvidence,
    EvidenceRef,
    EvidenceStatus,
    RankedHypothesis,
    _event_matches_workload,
    _investigation_validation_errors,
)


ACTUAL_URI = (
    "k8s://ok-ai/namespaces/ok14-evidence/pods/"
    "uc1-crashloop-6d9c8b7f5c-x2abc/logs?container=app"
)


def hypothesis(confidence: Confidence, uri: str = ACTUAL_URI) -> RankedHypothesis:
    return RankedHypothesis(
        hypothesis="Startup failed because the required DB_DSN key is missing.",
        confidence=confidence,
        evidence_refs=[uri],
        counter_evidence_status=CounterEvidence.none_found,
    )


class InvestigationValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.canonical = [
            EvidenceRef(
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
                    "k8s://ok-ai/namespaces/ok14-evidence/pods/fake/logs",
                )
            ],
        )
        self.assertIn("hypothesis 1 references unknown evidence", errors)


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


if __name__ == "__main__":
    unittest.main()
