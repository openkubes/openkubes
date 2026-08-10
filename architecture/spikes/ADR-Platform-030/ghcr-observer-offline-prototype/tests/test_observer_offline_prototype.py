import copy
import importlib.util
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ok141_observer_offline_prototype_test", HERE / "verify_observer_offline_prototype.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ObserverOfflinePrototypeTests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "observer-offline-prototype-v1.yaml"
        self.manifest = MODULE.V1.read_yaml_or_json(self.path)

    def assert_rejected(self, changed):
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_manifest_source_components_and_inertness_verify(self):
        self.assertTrue(MODULE.validate(self.manifest, self.path).startswith("sha256:"))

    def test_component_digest_tampering_fails_closed(self):
        changed = copy.deepcopy(self.manifest)
        changed["spec"]["components"]["evaluator"]["digest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)

    def test_active_workflow_or_index_cannot_be_preclaimed(self):
        for field in ("futureDeploymentPathPresent", "activeIndexPresent", "packageMutationPermissionPresent", "issueOrWebhookPermissionPresent"):
            changed = copy.deepcopy(self.manifest)
            changed["spec"]["workflowContract"][field] = True
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_live_proof_cannot_be_preclaimed(self):
        for field in ("liveRegistryCallPerformed", "workflowDeployed", "scheduleCreated", "packageReadAccessProven", "failedRunAlertProven", "missedRunDetectionProven"):
            changed = copy.deepcopy(self.manifest)
            changed["spec"]["proof"][field] = True
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_mutation_operation_cannot_be_added(self):
        changed = copy.deepcopy(self.manifest)
        changed["spec"]["evaluatorContract"]["mutationOperationsExposed"] = ["republish"]
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
        changed["spec"]["sourceAlertDecision"]["digest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)


if __name__ == "__main__":
    unittest.main()
