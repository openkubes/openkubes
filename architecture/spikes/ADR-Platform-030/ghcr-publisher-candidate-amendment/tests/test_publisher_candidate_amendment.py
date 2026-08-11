import copy
import hashlib
import importlib.util
import sys
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ok141_publisher_candidate_amendment", ROOT / "verify_publisher_candidate_amendment.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PublisherCandidateAmendmentTests(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / "publisher-candidate-amendment-v1.yaml"
        self.document = yaml.safe_load(self.path.read_text())

    def assert_rejected(self, changed):
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_amendment_reproduces_and_is_no_go(self):
        self.assertEqual(MODULE.validate(copy.deepcopy(self.document), self.path), "sha256:" + hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_source_ref_guard_is_required(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["candidate"]["jobSourceRefGuard"] = "refs/heads/*"
        self.assert_rejected(changed)

    def test_all_source_inputs_are_required(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["candidate"]["requiredInputs"].pop()
        self.assert_rejected(changed)

    def test_source_metadata_cannot_be_claimed_durable(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["candidate"]["sourceMetadataPersistedInOCIPayload"] = True
        self.assert_rejected(changed)

    def test_candidate_digest_tampering_is_rejected(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["candidate"]["digest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)

    def test_authorization_cannot_be_enabled(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["authorization"]["p0Granted"] = True
        self.assert_rejected(changed)

    def test_digest_file_is_current(self):
        self.assertEqual((ROOT / "publisher-candidate-amendment-v1.sha256").read_text().split()[0], hashlib.sha256(self.path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main(verbosity=2)
