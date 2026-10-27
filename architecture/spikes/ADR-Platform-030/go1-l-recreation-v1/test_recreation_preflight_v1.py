import copy
import tempfile
import unittest
from pathlib import Path

import yaml

import verify_recreation_preflight_v1 as VERIFY


HERE = Path(__file__).resolve().parent
PREFLIGHT = HERE / "recreation-preflight-v1.yaml"


class RecreationPreflightTests(unittest.TestCase):
    def write(self, value):
        handle = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", dir=HERE, delete=False)
        try:
            yaml.safe_dump(value, handle, sort_keys=False)
            return Path(handle.name)
        finally:
            handle.close()

    def test_preflight_is_valid_and_non_authorizing(self):
        value = VERIFY.verify(PREFLIGHT)
        self.assertFalse(any(value["spec"]["authorization"].values()))
        self.assertEqual(value["spec"]["correctedFixture"]["fixtureDigest"], "sha256:7536456a762880a78a37dcba76a5f3f0628140bd37b55d5fd62273c64e4cc3eb")

    def test_historical_v4_execution_artifacts_are_rejected(self):
        value = VERIFY.verify(PREFLIGHT)
        self.assertTrue(all(not item["allowedForRecreation"] for item in value["spec"]["rejectedHistoricalExecutionArtifacts"]))

    def test_sequence_or_provider_identity_tampering_fails_closed(self):
        original = VERIFY.V1.read_yaml_or_json(PREFLIGHT)
        for mutation in ("sequence", "secret"):
            value = copy.deepcopy(original)
            if mutation == "sequence":
                value["spec"]["requiredSequence"][1], value["spec"]["requiredSequence"][2] = value["spec"]["requiredSequence"][2], value["spec"]["requiredSequence"][1]
            else:
                value["spec"]["providerAccess"]["secretRef"]["name"] = "wrong"
            path = self.write(value)
            try:
                with self.assertRaises(VERIFY.PreflightError):
                    VERIFY.verify(path)
            finally:
                path.unlink()

    def test_any_authority_fails_closed(self):
        value = VERIFY.V1.read_yaml_or_json(PREFLIGHT)
        value["spec"]["authorization"]["recreationGranted"] = True
        path = self.write(value)
        try:
            with self.assertRaises(VERIFY.PreflightError):
                VERIFY.verify(path)
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
