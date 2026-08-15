import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "verify_go1_l_recovery_v1", ROOT / "verify_go1_l_recovery_v1.py"
)
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


class RecoveryProtocolTests(unittest.TestCase):
    def setUp(self):
        self.protocol = VERIFY.read(VERIFY.PROTOCOL)

    def validate_changed(self, changed):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "protocol.yaml"
            path.write_text(yaml.safe_dump(changed, sort_keys=False))
            return VERIFY.verify(path)

    def test_protocol_is_offline_and_blocked(self):
        self.assertEqual(VERIFY.verify(), VERIFY.digest(VERIFY.PROTOCOL))

    def test_patch_force_retry_and_recreate_cannot_be_enabled(self):
        mutations = {
            "patch": lambda d: d["spec"]["decision"].update(patchInPlaceAllowed=True),
            "recreate": lambda d: d["spec"]["decision"].update(automaticContinuationToRecreate=True),
            "force": lambda d: d["spec"]["stages"][1].update(force=True),
            "retry": lambda d: d["spec"]["stages"][3].update(automaticRetry=True),
            "stage": lambda d: d["spec"]["stages"][0].update(enabled=True),
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name):
                changed = copy.deepcopy(self.protocol)
                mutation(changed)
                with self.assertRaises(VERIFY.VerificationError):
                    self.validate_changed(changed)

    def test_wrong_fixture_or_source_identity_fails_closed(self):
        mutations = {
            "fixture": lambda d: d["spec"]["correctedBaseline"]["fixture"].update(fileDigest="sha256:" + "0" * 64),
            "r": lambda d: d["spec"]["correctedBaseline"]["fixture"].update(R="sha256:" + "1" * 64),
            "submitter": lambda d: d["spec"]["failedExecution"]["submitter"].update(digest="sha256:" + "2" * 64),
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name):
                changed = copy.deepcopy(self.protocol)
                mutation(changed)
                with self.assertRaises(VERIFY.VerificationError):
                    self.validate_changed(changed)

    def test_public_protocol_has_no_live_uids_or_credentials(self):
        content = VERIFY.PROTOCOL.read_text().lower()
        self.assertNotIn("client-key-data", content)
        self.assertNotIn("client-certificate-data", content)
        self.assertNotIn("private key", content)
        self.assertNotRegex(content, r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


if __name__ == "__main__":
    unittest.main()
