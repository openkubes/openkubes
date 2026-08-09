import hashlib
import json
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class M0AProtocolTests(unittest.TestCase):
    def setUp(self):
        self.protocol = yaml.safe_load((ROOT / "m0a-protocol.yaml").read_text())
        self.spec = self.protocol["spec"]
        self.inventory = yaml.safe_load(
            (ROOT / "caaph-installation-inventory.yaml").read_text()
        )["spec"]
        self.candidate = yaml.safe_load(
            (ROOT / "helmchartproxy-v3-candidate.yaml").read_text()
        )
        self.rbac = yaml.safe_load((ROOT / "caaph-rbac-review.yaml").read_text())["spec"]
        self.submitter_role = yaml.safe_load(
            (ROOT / "submitter-role-candidate.yaml").read_text()
        )

    def test_authorization_is_fail_closed(self):
        auth = self.spec["authorization"]
        self.assertEqual(self.spec["protocolState"], "BLOCKED")
        self.assertEqual(auth["decision"], "NO-GO")
        self.assertFalse(auth["m0aGranted"])
        self.assertFalse(auth["go1Granted"])
        self.assertIsNone(auth["authorizedProtocolDigest"])
        self.assertTrue(all(not phase["enabled"] for phase in self.spec["phases"]))
        self.assertFalse(self.spec["installation"]["applyEnabled"])
        self.assertFalse(self.spec["candidate"]["submitEnabled"])

    def test_current_fixture_identities_are_exact(self):
        fixture = self.spec["fixture"]
        annotations = self.candidate["metadata"]["annotations"]
        self.assertEqual(annotations["openkubes.io/intent-revision"], fixture["R"])
        self.assertEqual(annotations["openkubes.io/enablement-revision"], fixture["E"])
        self.assertEqual(annotations["openkubes.io/execution-fixture"], fixture["fixtureDigest"])

    def test_official_oci_content_equals_fixture_artifact(self):
        resolution = self.spec["artifactResolution"]
        self.assertEqual(resolution["chartContentDigest"], resolution["fixtureArtifactDigest"])
        self.assertTrue(resolution["equalityProvenReadOnly"])
        self.assertFalse(resolution["caaphDigestFieldAvailable"])
        self.assertEqual(
            resolution["enforcement"], "EXTERNAL-EVIDENCE-NOT-CONTROLLER-ENFORCED"
        )
        self.assertEqual(
            self.candidate["metadata"]["annotations"]["openkubes.io/digest-enforcement"],
            "external-evidence-required",
        )

    def test_installation_inventory_is_exact_and_disabled(self):
        self.assertEqual(self.inventory["objectInventory"]["total"], 19)
        self.assertEqual(sum(self.inventory["objectInventory"]["byKind"].values()), 19)
        self.assertFalse(self.inventory["authorization"]["applyEnabled"])
        self.assertFalse(self.inventory["baseline"]["caaphCRDsPresent"])
        self.assertFalse(self.inventory["baseline"]["caaphControllerPresent"])
        self.assertEqual(
            self.inventory["controllerImage"]["linuxAmd64Digest"],
            self.spec["installation"]["controllerImagePlatformDigest"],
        )

    def test_controller_and_submitter_rbac_boundaries_do_not_blur(self):
        sensitive = self.rbac["sensitiveCapabilities"]
        self.assertTrue(
            any(item["resources"] == ["secrets"] and "list" in item["verbs"] for item in sensitive)
        )
        denied = self.rbac["submitterCandidate"]["explicitlyDenied"]
        self.assertIn("arbitrary Secret get/list/watch", denied)
        self.assertIn("helmreleaseproxies create/patch/update/delete", denied)
        self.assertEqual(self.rbac["result"]["controllerRole"], "SECURITY-REVIEW-REQUIRED")
        self.assertEqual(self.rbac["result"]["submitterRole"], "RENDERED-NOT-PROVEN")
        self.assertEqual(self.rbac["result"]["exactObjectAdmission"], "UNRESOLVED")
        self.assertEqual(self.rbac["result"]["m0a"], "NOT-GRANTED")

    def test_submitter_role_is_namespace_bounded_without_secret_or_hrp_access(self):
        self.assertEqual(self.submitter_role["kind"], "Role")
        self.assertEqual(self.submitter_role["metadata"]["namespace"], "disposable-ok141")
        self.assertEqual(
            self.submitter_role["metadata"]["annotations"]["openkubes.io/candidate-status"],
            "blocked-no-go",
        )
        resources = {
            resource
            for rule in self.submitter_role["rules"]
            for resource in rule["resources"]
        }
        self.assertEqual(resources, {"helmchartproxies"})
        self.assertNotIn("secrets", resources)
        self.assertNotIn("helmreleaseproxies", resources)
        update_rule = next(
            rule for rule in self.submitter_role["rules"] if "update" in rule["verbs"]
        )
        self.assertEqual(update_rule["resourceNames"], ["disposable-ok141-cilium"])
        self.assertEqual(self.spec["submitter"]["roleBindingStatus"], "ABSENT-BY-DESIGN")

    def test_candidate_is_current_but_not_authorized(self):
        self.assertEqual(
            self.candidate["metadata"]["annotations"]["openkubes.io/candidate-status"],
            "blocked-no-go",
        )
        self.assertEqual(self.candidate["spec"]["repoURL"], "oci://quay.io/cilium/charts")
        self.assertEqual(self.candidate["spec"]["version"], "1.19.6")
        self.assertEqual(self.candidate["spec"]["reconcileStrategy"], "Continuous")
        self.assertEqual(self.spec["candidate"]["status"], "BLOCKED-NOT-AUTHORIZED")

    def test_candidate_values_equal_bound_enablement_profile(self):
        profile = json.loads(
            (
                ROOT.parent
                / "harness/profiles/enablement/cilium-fixture-v2/profile.json"
            ).read_text()
        )
        expected_values = yaml.safe_load(
            (
                ROOT.parent
                / "harness/profiles/enablement/cilium-fixture-v2/values.yaml"
            ).read_text()
        )
        actual_values = yaml.safe_load(self.candidate["spec"]["valuesTemplate"])
        encoded = json.dumps(
            actual_values, sort_keys=True, separators=(",", ":")
        ).encode()
        digest = "sha256:" + hashlib.sha256(encoded).hexdigest()
        self.assertEqual(actual_values, expected_values)
        self.assertEqual(digest, profile["package"]["valuesDigest"])

    def test_protocol_digest_is_current(self):
        actual = "sha256:" + hashlib.sha256(
            (ROOT / "m0a-protocol.yaml").read_bytes()
        ).hexdigest()
        self.assertEqual((ROOT / "m0a-protocol.sha256").read_text().strip(), actual)


if __name__ == "__main__":
    unittest.main()
