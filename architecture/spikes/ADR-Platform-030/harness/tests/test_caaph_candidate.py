import hashlib
import json
import unittest
from pathlib import Path

import yaml


HARNESS_DIR = Path(__file__).resolve().parents[1]
CANDIDATE_DIR = HARNESS_DIR / "candidates/caaph-v0.6.4"


def semantic_yaml_digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class CAAPHCandidateTests(unittest.TestCase):
    def setUp(self):
        self.candidate = yaml.safe_load(
            (CANDIDATE_DIR / "helmchartproxy-candidate.yaml").read_text()
        )
        self.expected = json.loads(
            (CANDIDATE_DIR / "expected-helmreleaseproxy.json").read_text()
        )
        self.profile = json.loads(
            (HARNESS_DIR / "profiles/enablement/cilium-fixture-v2/profile.json").read_text()
        )
        self.fixture = json.loads(
            (HARNESS_DIR / "fixtures/execution/phase-r-v2.json").read_text()
        )

    def test_candidate_is_explicitly_non_submittable(self):
        annotations = self.candidate["metadata"]["annotations"]
        self.assertEqual(annotations["openkubes.io/candidate-status"], "blocked-no-go")
        self.assertEqual(
            self.candidate["spec"]["repoURL"],
            "oci://registry.invalid/openkubes/charts",
        )
        self.assertEqual(self.expected["authorization"], "NO-GO")

    def test_candidate_carries_current_fixture_identities(self):
        annotations = self.candidate["metadata"]["annotations"]
        self.assertEqual(
            annotations["openkubes.io/intent-revision"], self.fixture["contract"]["R"]
        )
        self.assertEqual(
            annotations["openkubes.io/enablement-revision"],
            self.fixture["enablement"]["E"],
        )
        self.assertEqual(
            annotations["openkubes.io/execution-fixture"], self.fixture["fixtureDigest"]
        )
        self.assertEqual(
            annotations["openkubes.io/chart-artifact-digest"],
            self.profile["package"]["artifactDigest"],
        )
        self.assertEqual(
            annotations["openkubes.io/values-digest"],
            self.profile["package"]["valuesDigest"],
        )

    def test_values_and_release_semantics_match_e_prime(self):
        values = yaml.safe_load(self.candidate["spec"]["valuesTemplate"])
        expected_values = yaml.safe_load(
            (HARNESS_DIR / "profiles/enablement/cilium-fixture-v2/values.yaml").read_text()
        )
        self.assertEqual(values, expected_values)
        self.assertEqual(semantic_yaml_digest(values), self.profile["package"]["valuesDigest"])
        self.assertEqual(self.candidate["spec"]["chartName"], "cilium")
        self.assertEqual(
            self.candidate["spec"]["version"], self.profile["package"]["version"]
        )
        self.assertEqual(self.candidate["spec"]["reconcileStrategy"], "Continuous")

    def test_target_is_bounded_but_requires_runtime_uid_proof(self):
        self.assertEqual(self.candidate["metadata"]["namespace"], "disposable-ok141")
        self.assertEqual(
            self.candidate["spec"]["clusterSelector"]["matchLabels"],
            {"openkubes.io/type": "talos", "openkubes.io/provider": "kubevirt"},
        )
        acceptance = self.expected["runtimeAcceptance"]
        self.assertEqual(acceptance["matchingClusterCount"], 1)
        self.assertTrue(acceptance["requireExactClusterUID"])
        self.assertTrue(acceptance["requireCurrentObservedGeneration"])
        self.assertEqual(
            self.expected["object"]["labels"],
            {
                "cluster.x-k8s.io/cluster-name": "disposable-ok141",
                "helmreleaseproxy.addons.cluster.x-k8s.io/helmchartproxy-name":
                    "disposable-ok141-cilium",
            },
        )

    def test_helm_revision_is_not_e_prime(self):
        acceptance = self.expected["runtimeAcceptance"]
        self.assertFalse(acceptance["helmRevisionIsEnablementRevision"])
        self.assertTrue(acceptance["requireIndependentEnablementRevisionCorrelation"])


if __name__ == "__main__":
    unittest.main()
