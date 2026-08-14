from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


CONFORMANCE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONFORMANCE_DIR))

import verify  # noqa: E402


class ConformanceMatrixTests(unittest.TestCase):
    def test_repository_matrix_is_conformant(self) -> None:
        verify.verify_all()

    def test_write_verb_is_rejected(self) -> None:
        documents = copy.deepcopy(verify.load_rbac_documents())
        role = verify.one_kind(documents, "ClusterRole")
        role["rules"][0]["verbs"].append("create")

        with self.assertRaisesRegex(verify.ConformanceError, "verbs present"):
            verify.verify_rbac_documents(documents)

    def test_secret_access_is_rejected(self) -> None:
        documents = copy.deepcopy(verify.load_rbac_documents())
        role = verify.one_kind(documents, "ClusterRole")
        role["rules"][0]["resources"].append("secrets")

        with self.assertRaisesRegex(verify.ConformanceError, "Secrets"):
            verify.verify_rbac_documents(documents)

    def test_wildcard_access_is_rejected(self) -> None:
        documents = copy.deepcopy(verify.load_rbac_documents())
        role = verify.one_kind(documents, "ClusterRole")
        role["rules"][0]["resources"].append("*")

        with self.assertRaisesRegex(verify.ConformanceError, "wildcards"):
            verify.verify_rbac_documents(documents)

    def test_silent_capability_omission_is_rejected(self) -> None:
        profiles, responses = verify.load_matrix()
        response = copy.deepcopy(responses[0])
        response["evidence"] = [
            item for item in response["evidence"] if item["type"] != "node_shell"
        ]

        with self.assertRaisesRegex(verify.ConformanceError, "silently omitted"):
            verify.verify_response(profiles[0], response)

    def test_unavailable_evidence_without_reason_is_rejected(self) -> None:
        profiles, responses = verify.load_matrix()
        response = copy.deepcopy(responses[0])
        response["evidence"][0]["reason"] = ""

        with self.assertRaisesRegex(verify.ConformanceError, "has no reason"):
            verify.verify_response(profiles[0], response)

    def test_available_evidence_without_uri_is_rejected(self) -> None:
        profiles, responses = verify.load_matrix()
        response = copy.deepcopy(responses[1])
        response["evidence"][0]["uri"] = None

        with self.assertRaisesRegex(verify.ConformanceError, "has no evidence URI"):
            verify.verify_response(profiles[1], response)

    def test_duplicate_evidence_ids_are_rejected(self) -> None:
        profiles, responses = verify.load_matrix()
        response = copy.deepcopy(responses[0])
        response["evidence"][1]["id"] = response["evidence"][0]["id"]

        with self.assertRaisesRegex(verify.ConformanceError, "present and unique"):
            verify.verify_response(profiles[0], response)

    def test_normative_evidence_bundle_drift_is_rejected(self) -> None:
        _, responses = verify.load_matrix()
        response = copy.deepcopy(responses[0])
        response.pop("invocation_id")

        with self.assertRaisesRegex(verify.ConformanceError, "invocation_id"):
            verify.verify_response_schema(response)

    def test_distribution_contract_shape_drift_is_rejected(self) -> None:
        _, responses = verify.load_matrix()
        response = copy.deepcopy(responses[1])
        response["distribution_specific_payload"] = {}

        with self.assertRaisesRegex(verify.ConformanceError, "different contract fields"):
            verify.verify_contract_identity([responses[0], response])

    def test_distribution_capability_key_drift_is_rejected(self) -> None:
        profiles, _ = verify.load_matrix()
        profile = copy.deepcopy(profiles[1])
        profile["provider_capabilities"]["distribution_only"] = True

        with self.assertRaisesRegex(
            verify.ConformanceError, "different provider capability keys"
        ):
            verify.verify_capability_identity([profiles[0], profile])


if __name__ == "__main__":
    unittest.main()
