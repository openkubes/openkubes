import json
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


class DefaultAudienceClosureTests(unittest.TestCase):
    def test_closure_proves_default_audience_and_preserves_boundaries(self):
        value = json.loads((HERE / "default-audience-closure-v1.json").read_text())
        self.assertEqual(value["result"], "PASS-DEFAULT-AUDIENCE-DIAGNOSTIC")
        self.assertEqual(value["classification"], "SUCCESS")
        self.assertEqual(value["requestedAudienceCount"], 0)
        self.assertFalse(value["returnedAudienceMatchesOldBoundAudience"])
        self.assertTrue(all(value["claimChecks"].values()))
        self.assertTrue(value["targetProbeSucceeded"])
        boundaries = value["boundaries"]
        self.assertFalse(boundaries["persistentObjectCreated"])
        self.assertFalse(boundaries["credentialPayloadPublished"])
        self.assertFalse(boundaries["rawResponsePublished"])
        self.assertTrue(boundaries["adminKubeconfigRemoved"])
        self.assertTrue(boundaries["tokenKubeconfigRemoved"])
        self.assertFalse(boundaries["retryPerformed"])
        self.assertFalse(boundaries["happyRunResumed"])


if __name__ == "__main__":
    unittest.main()
