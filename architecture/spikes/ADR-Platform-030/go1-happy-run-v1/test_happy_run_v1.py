import datetime as dt
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("happy", HERE / "bounded_happy_run_v1.py")
happy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(happy)


class HappyRunTests(unittest.TestCase):
    def test_candidate_sequence_and_no_go(self):
        plan = happy.plan()
        self.assertEqual(plan["sequence"], ["PF", "G1", "LIFECYCLE", "G3", "NETWORK", "BIND", "TARGET-ACCESS", "PLATFORM-CREDENTIALS", "TOKEN-REGISTRATION", "APPLICATIONS", "PLATFORM-READY"])
        self.assertEqual(plan["authorization"], "NO-GO")

    def grant(self):
        now = dt.datetime.now(dt.timezone.utc)
        spec = {"decision": "GO", "authority": "github:arashkaffamanesh", "singleRun": True, "consumed": False, "candidateDigest": happy.sha(happy.CANDIDATE), "protocolDigest": happy.validate_candidate()["spec"]["protocolDigest"], "fixtureDigest": happy.validate_candidate()["spec"]["fixture"]["fixtureDigest"], "grantID": "ok141-happy-v1-test", "runID": "ok141-happy-test-v1", "issuedAt": happy.iso(now - dt.timedelta(minutes=1)), "expiresAt": happy.iso(now + dt.timedelta(minutes=30))}
        spec.update({key: True for key in happy.GRANTED}); spec.update({key: False for key in happy.DENIED})
        return {"apiVersion": "authorization.openkubes.io/v1alpha1", "kind": "GO1HappyRunGrant", "spec": spec}

    def write(self, value):
        file = tempfile.NamedTemporaryFile("w", delete=False); json.dump(value, file); file.close(); return Path(file.name)

    def test_exact_grant_validates(self):
        path = self.write(self.grant())
        try: self.assertEqual(happy.validate_grant(happy.CANDIDATE, path)["spec"]["decision"], "GO")
        finally: path.unlink()

    def test_retry_or_missing_capability_fails_closed(self):
        value = self.grant(); value["spec"]["retryGranted"] = True
        path = self.write(value)
        try:
            with self.assertRaises(happy.HappyRunError): happy.validate_grant(happy.CANDIDATE, path)
        finally: path.unlink()
        value = self.grant(); value["spec"]["capabilityTestGranted"] = False
        path = self.write(value)
        try:
            with self.assertRaises(happy.HappyRunError): happy.validate_grant(happy.CANDIDATE, path)
        finally: path.unlink()


if __name__ == "__main__": unittest.main()
