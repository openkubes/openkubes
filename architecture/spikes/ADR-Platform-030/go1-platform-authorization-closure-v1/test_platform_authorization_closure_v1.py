import json
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


class ClosureTests(unittest.TestCase):
    def test_closure_is_complete_and_minimal(self):
        value = json.loads((HERE / "platform-authorization-closure-v1.json").read_text())
        self.assertEqual(value["findingCount"], 3)
        self.assertEqual(value["unparsedAuthorizationConditionCount"], 0)
        self.assertTrue(value["remediationDesignReady"])
        self.assertEqual({item["verb"] for item in value["normalizedFindings"]}, {"list"})
        self.assertFalse(value["rawMessagesPublished"])
        self.assertFalse(value["mutationPerformed"])


if __name__ == "__main__": unittest.main()
