import copy
import hashlib
import importlib.util
import sys
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ok141_publisher_durable_checkpoint", ROOT / "verify_publisher_durable_correlation.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class DurableCorrelationCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / "publisher-durable-correlation-v1.yaml"
        self.document = yaml.safe_load(self.path.read_text())

    def rejected(self, changed):
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_checkpoint_is_reproducible_and_no_go(self):
        digest = MODULE.validate(copy.deepcopy(self.document), self.path)
        self.assertEqual(digest, "sha256:" + hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_candidate_tampering_is_rejected(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["components"]["candidateWorkflow"]["digest"] = "sha256:" + "0" * 64
        self.rejected(changed)

    def test_durable_correlation_cannot_be_disabled(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["correlationContract"]["transportDigestBindsCorrelation"] = False
        self.rejected(changed)

    def test_live_publication_cannot_be_claimed(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["proof"]["livePublicationPerformed"] = True
        self.rejected(changed)

    def test_authorization_cannot_be_enabled(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["authorization"]["p0Granted"] = True
        self.rejected(changed)

    def test_digest_file_is_current(self):
        expected = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.assertEqual((ROOT / "publisher-durable-correlation-v1.sha256").read_text().split()[0], expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
