import hashlib
import importlib.util
import json
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SPIKE = ROOT.parent


def documents(path):
    return [item for item in yaml.safe_load_all(path.read_text()) if item]


class M0BProtocolTests(unittest.TestCase):
    def setUp(self):
        self.spec = yaml.safe_load((ROOT / "m0b-protocol.yaml").read_text())["spec"]
        self.install = yaml.safe_load(
            (ROOT / "argocd-installation-inventory.yaml").read_text()
        )["spec"]
        self.inventory = json.loads((ROOT / "platform-rendered-inventory.json").read_text())
        self.project = yaml.safe_load((ROOT / "appproject-v3-candidate.yaml").read_text())
        self.registration = yaml.safe_load(
            (ROOT / "cluster-registration-v3-candidate.yaml").read_text()
        )
        self.rbac = documents(ROOT / "target-rbac-v3-candidate.yaml")
        self.assertion = json.loads((ROOT / "platformready-v3-assertion.json").read_text())

    def test_authorization_is_fail_closed(self):
        auth = self.spec["authorization"]
        self.assertEqual(self.spec["protocolState"], "BLOCKED")
        self.assertEqual(auth["decision"], "NO-GO")
        self.assertFalse(auth["m0bGranted"])
        self.assertFalse(auth["go1Granted"])
        self.assertTrue(all(not phase["enabled"] for phase in self.spec["phases"]))
        self.assertFalse(self.spec["installation"]["applyEnabled"])
        self.assertFalse(self.spec["candidates"]["submitEnabled"])

    def test_current_fixture_identities_are_exact(self):
        fixture = self.spec["fixture"]
        annotations = self.project["metadata"]["annotations"]
        self.assertEqual(annotations["openkubes.io/intent-revision"], fixture["R"])
        self.assertEqual(annotations["openkubes.io/platform-revision"], fixture["P"])
        self.assertEqual(annotations["openkubes.io/execution-fixture"], fixture["fixtureDigest"])
        self.assertEqual(self.assertion["platformRevision"], fixture["P"])

    def test_installation_inventory_is_exact_absent_and_disabled(self):
        self.assertEqual(self.install["objectInventory"]["manifestObjects"], 61)
        self.assertEqual(sum(self.install["objectInventory"]["byKind"].values()), 61)
        self.assertEqual(self.install["objectInventory"]["total"], 65)
        self.assertEqual(len(self.install["images"]), 4)
        self.assertTrue(all(item["linuxAmd64Digest"].startswith("sha256:") for item in self.install["images"]))
        self.assertFalse(self.install["baseline"]["argocdCRDsPresent"])
        self.assertFalse(self.install["baseline"]["argocdControllerPresent"])
        self.assertFalse(self.install["authorization"]["applyEnabled"])

    def test_rendered_inventory_exposes_cluster_and_two_namespace_scope(self):
        self.assertEqual(self.inventory["objectCount"], 120)
        self.assertEqual(self.inventory["sourceProvenance"], "LOCAL-IGNORED-DEPENDENCIES-NOT-AUTHORITATIVE")
        self.assertEqual(len(self.inventory["dependencyArtifacts"]), 7)
        self.assertTrue(all(not item["trackedAtSourceCommit"] for item in self.inventory["dependencyArtifacts"]))
        namespaces = {item["namespace"] for item in self.inventory["objects"] if item["namespace"]}
        self.assertEqual(namespaces, {"ok-observability", "kube-system"})
        cluster_kinds = {item["kind"] for item in self.inventory["objects"] if item["namespace"] is None}
        self.assertEqual(cluster_kinds, {
            "CustomResourceDefinition", "ClusterRole", "ClusterRoleBinding",
            "MutatingWebhookConfiguration", "ValidatingWebhookConfiguration",
        })

    def test_appproject_is_exact_and_has_no_wildcards(self):
        spec = self.project["spec"]
        destinations = {(item["name"], item["namespace"]) for item in spec["destinations"]}
        self.assertEqual(destinations, {
            ("disposable-ok141", "ok-observability"),
            ("disposable-ok141", "kube-system"),
        })
        rules = spec["clusterResourceWhitelist"] + spec["namespaceResourceWhitelist"]
        self.assertTrue(all(item["group"] != "*" and item["kind"] != "*" for item in rules))
        def group(item):
            return item["apiVersion"].split("/", 1)[0] if "/" in item["apiVersion"] else ""
        expected_cluster = {
            (group(item), item["kind"])
            for item in self.inventory["objects"]
            if item["namespace"] is None
        } | {("", "Namespace")}
        expected_namespaced = {
            (group(item), item["kind"])
            for item in self.inventory["objects"]
            if item["namespace"] is not None
        }
        actual_cluster = {(item["group"], item["kind"]) for item in spec["clusterResourceWhitelist"]}
        actual_namespaced = {(item["group"], item["kind"]) for item in spec["namespaceResourceWhitelist"]}
        self.assertEqual(actual_cluster, expected_cluster)
        self.assertEqual(actual_namespaced, expected_namespaced)

    def test_registration_is_non_operational_and_requires_cluster_resources(self):
        data = self.registration["stringData"]
        self.assertEqual(data["server"], "https://api.invalid")
        self.assertEqual(data["clusterResources"], "true")
        self.assertEqual(set(data["namespaces"].split(",")), {"ok-observability", "kube-system"})
        self.assertNotIn("config", data)
        self.assertFalse(self.spec["candidates"]["registration"]["containsCredential"])

    def test_target_rbac_has_no_binding_wildcard_or_unbounded_namespaced_role(self):
        self.assertEqual([item["kind"] for item in self.rbac], ["ClusterRole", "Role", "Role"])
        self.assertNotIn("RoleBinding", {item["kind"] for item in self.rbac})
        for item in self.rbac:
            for rule in item["rules"]:
                self.assertNotIn("*", rule["apiGroups"])
                self.assertNotIn("*", rule["resources"])
                self.assertNotIn("*", rule["verbs"])
        namespaces = {item["metadata"].get("namespace") for item in self.rbac if item["kind"] == "Role"}
        self.assertEqual(namespaces, {"ok-observability", "kube-system"})
        self.assertEqual(self.spec["targetAuthorization"]["roleBindings"], "ABSENT-BY-DESIGN")

    def test_platformready_fails_closed_on_transitive_source_identity(self):
        self.assertTrue(self.assertion["sourceProof"]["requireTransitiveArtifactIdentity"])
        self.assertEqual(self.assertion["sourceProof"]["currentTransitiveArtifactIdentity"], "BLOCKED")
        self.assertFalse(self.assertion["capabilityProof"]["argoHealthAloneIsCapabilityProof"])
        self.assertEqual(len(self.assertion["requiredApplications"]), 3)

    def test_local_render_snapshot_replays_when_source_is_available(self):
        source = SPIKE.parents[3] / "ok-observability"
        if not (source / ".git").is_dir():
            self.skipTest("ok-observability sibling source is not available")
        module_path = ROOT / "render_platform_inventory.py"
        spec = importlib.util.spec_from_file_location("ok141_m0b_render", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.render(source), self.inventory)

    def test_protocol_digest_is_current(self):
        actual = "sha256:" + hashlib.sha256((ROOT / "m0b-protocol.yaml").read_bytes()).hexdigest()
        self.assertEqual((ROOT / "m0b-protocol.sha256").read_text().strip(), actual)


if __name__ == "__main__":
    unittest.main()
