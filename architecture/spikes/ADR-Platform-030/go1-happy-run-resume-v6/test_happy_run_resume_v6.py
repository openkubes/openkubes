import importlib.util
import sys
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_happy_resume_v6_test", HERE / "bounded_happy_run_resume_v6.py")
RESUME = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RESUME
assert SPEC.loader is not None
SPEC.loader.exec_module(RESUME)


class HappyRunResumeV6Tests(unittest.TestCase):
    def test_candidate_is_inert_and_binds_freshness(self):
        candidate = RESUME.validate_candidate()
        self.assertEqual(candidate["spec"]["authorization"]["decision"], "NO-GO")
        self.assertEqual(candidate["spec"]["cacheFreshness"]["candidateDigest"], RESUME.FRESH_DIGEST)
        self.assertFalse(candidate["spec"]["identityImpact"]["fixtureDigestChanged"])

    def test_template_remains_no_go(self):
        value = yaml.safe_load((HERE / "happy-run-resume-grant-v6.template.yaml").read_text())
        self.assertEqual(value["spec"]["decision"], "NO-GO")
        self.assertTrue(all(not item for key, item in value["spec"].items() if key.endswith("Granted")))

    def test_new_output_is_exclusive_from_v5(self):
        self.assertNotEqual(RESUME.NEW_NETWORK_OUTPUT, RESUME.V5.NEW_NETWORK_OUTPUT)


if __name__ == "__main__": unittest.main()

