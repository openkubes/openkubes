from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import verify_m0a_v7_security as module  # noqa: E402


class SecurityTests(unittest.TestCase):
    def test_security_package_is_non_authorizing(self) -> None:
        result = module.verify()
        self.assertEqual(result["state"], "BLOCKED-OFFLINE-CANDIDATE")
        self.assertEqual(result["risks"], 5)
        self.assertEqual(result["separateGrantDomains"], 4)
        self.assertFalse(result["mutationAuthorized"])
        self.assertFalse(result["clusterContacted"])


if __name__ == "__main__":
    unittest.main()
