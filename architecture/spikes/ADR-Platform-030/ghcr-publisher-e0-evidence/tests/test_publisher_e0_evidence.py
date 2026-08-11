import copy
import hashlib
import importlib.util
import sys
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ok141_publisher_e0_evidence", ROOT / "verify_publisher_e0_evidence.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PublisherE0EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / "publisher-e0-evidence-v1.yaml"
        self.document = yaml.safe_load(self.path.read_text())

    def rejected(self, changed):
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_e0_evidence_is_reproducible_and_no_go(self):
        digest = MODULE.validate(copy.deepcopy(self.document), self.path)
        self.assertEqual(digest, "sha256:" + hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_admin_bypass_cannot_be_hidden(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["observedState"]["canAdminsBypass"] = False
        self.rejected(changed)

    def test_secret_cannot_be_claimed(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["observedState"]["environmentSecretsCount"] = 1
        self.rejected(changed)

    def test_workflow_cannot_be_claimed_active(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["observedState"]["activePublisherWorkflow"]["state"] = "PRESENT"
        self.rejected(changed)

    def test_w0_cannot_be_granted(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["authorization"]["w0Granted"] = True
        self.rejected(changed)

    def test_digest_file_is_current(self):
        expected = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.assertEqual((ROOT / "publisher-e0-evidence-v1.sha256").read_text().split()[0], expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
