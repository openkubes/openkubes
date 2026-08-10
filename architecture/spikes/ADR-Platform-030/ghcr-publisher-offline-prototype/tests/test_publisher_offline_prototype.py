import copy
import importlib.util
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ok141_publisher_offline_prototype_test", HERE / "verify_publisher_offline_prototype.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PublisherOfflinePrototypeTests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "publisher-offline-prototype-v1.yaml"
        self.manifest = MODULE.V1.read_yaml_or_json(self.path)

    def assert_rejected(self, changed):
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_manifest_source_components_and_inertness_verify(self):
        self.assertTrue(MODULE.validate(self.manifest, self.path).startswith("sha256:"))

    def test_component_or_supply_chain_tampering_fails_closed(self):
        changed = copy.deepcopy(self.manifest)
        changed["spec"]["components"]["plannerAndVerifier"]["digest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.manifest)
        changed["spec"]["supplyChain"]["oras"]["assetDigest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)

    def test_active_workflow_environment_or_delete_cannot_be_preclaimed(self):
        for field in ("futureDeploymentPathPresent", "environmentPresent", "packageDeletePermissionPresent", "issueOrWebhookPermissionPresent"):
            changed = copy.deepcopy(self.manifest)
            changed["spec"]["workflowContract"][field] = True
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_live_proof_cannot_be_preclaimed(self):
        for field in ("livePackageWritePerformed", "liveAttestationPerformed", "livePullBackPerformed", "workflowDeployed", "environmentCreated", "credentialAuthorized"):
            changed = copy.deepcopy(self.manifest)
            changed["spec"]["proof"][field] = True
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_tag_or_pullback_authority_cannot_be_weakened(self):
        changed = copy.deepcopy(self.manifest)
        changed["spec"]["publicationContract"]["tagAuthority"] = "AUTHORITATIVE"
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.manifest)
        changed["spec"]["publicationContract"]["pullBackReference"] = "TAG"
        self.assert_rejected(changed)

    def test_any_authorization_fails_closed(self):
        for field in self.manifest["spec"]["authorization"]:
            if field == "decision":
                continue
            changed = copy.deepcopy(self.manifest)
            changed["spec"]["authorization"][field] = True
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_source_digest_tampering_fails_closed(self):
        changed = copy.deepcopy(self.manifest)
        changed["spec"]["sourceObserverPrototype"]["digest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)


if __name__ == "__main__":
    unittest.main()
