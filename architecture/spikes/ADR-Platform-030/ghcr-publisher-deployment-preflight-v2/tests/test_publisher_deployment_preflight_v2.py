import copy
import hashlib
import importlib.util
import sys
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ok141_publisher_preflight_v2", ROOT / "verify_publisher_deployment_preflight_v2.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PublisherDeploymentPreflightV2Tests(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / "publisher-deployment-preflight-v2.yaml"
        self.document = yaml.safe_load(self.path.read_text())

    def rejected(self, changed):
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_preflight_is_reproducible_and_no_go(self):
        digest = MODULE.validate(copy.deepcopy(self.document), self.path)
        self.assertEqual(digest, "sha256:" + hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_environment_cannot_be_claimed_present(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["readOnlyObservation"]["environmentState"] = "PRESENT"
        self.rejected(changed)

    def test_offline_closure_cannot_be_weakened(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["offlineClosure"]["durableSourceCorrelation"] = "UNRESOLVED"
        self.rejected(changed)

    def test_later_gate_cannot_be_granted(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["gateSequence"][1]["status"] = "GRANTED"
        self.rejected(changed)

    def test_e0_cannot_authorize_later_gates(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["nextDecision"]["authorizesLaterGates"] = True
        self.rejected(changed)

    def test_external_write_cannot_be_authorized(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["authorization"]["externalWriteAuthorized"] = True
        self.rejected(changed)

    def test_digest_file_is_current(self):
        expected = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.assertEqual((ROOT / "publisher-deployment-preflight-v2.sha256").read_text().split()[0], expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
