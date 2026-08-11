import copy
import hashlib
import importlib.util
import sys
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ok141_publisher_deployment_preflight",
    ROOT / "verify_publisher_deployment_preflight.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PublisherDeploymentPreflightTests(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / "publisher-deployment-preflight-v1.yaml"
        self.document = yaml.safe_load(self.path.read_text())

    def test_preflight_is_current_and_no_go(self):
        self.assertEqual(
            MODULE.validate(copy.deepcopy(self.document), self.path),
            "sha256:" + hashlib.sha256(self.path.read_bytes()).hexdigest(),
        )

    def test_implicit_environment_creation_fails_closed(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["environmentCandidate"]["creationByWorkflowForbidden"] = False
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_reviewer_identity_is_exact(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["environmentCandidate"]["reviewers"][0]["id"] = 1
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_main_only_policy_is_exact(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["environmentCandidate"]["deploymentBranchPolicy"]["exactPattern"] = "*"
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_gate_order_cannot_collapse(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["gateSequence"][1]["dependsOn"] = []
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_no_gate_is_granted(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["gateSequence"][0]["status"] = "GRANTED"
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_authorization_cannot_enable_external_write(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["authorization"]["externalWriteAuthorized"] = True
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_digest_file_is_current(self):
        expected = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.assertEqual((ROOT / "publisher-deployment-preflight-v1.sha256").read_text().split()[0], expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
