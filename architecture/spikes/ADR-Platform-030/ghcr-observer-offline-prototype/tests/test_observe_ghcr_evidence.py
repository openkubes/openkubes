import copy
import datetime as dt
import importlib.util
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ok141_observe_ghcr_evidence_test", HERE / "observe_ghcr_evidence.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ObserveGHCREvidenceTests(unittest.TestCase):
    def setUp(self):
        self.index_path = HERE / "fixtures" / "active-index.json"
        self.observation_path = HERE / "fixtures" / "present-observation.json"
        self.index = MODULE.load_index(self.index_path)
        self.observation = json.loads(self.observation_path.read_text())
        self.now = dt.datetime(2026, 8, 10, 18, 11, tzinfo=dt.timezone.utc)

    def test_exact_digest_is_present(self):
        result = MODULE.evaluate(self.index, self.observation, self.now)
        self.assertEqual((result["status"], result["reason"]), ("OBSERVED-PRESENT", "ExactDigestPresent"))

    def test_missing_denied_and_unverifiable_fail(self):
        reasons = {"MISSING": "DigestMissing", "DENIED": "PackageReadDenied", "UNVERIFIABLE": "EvidenceUnverifiable"}
        for status, reason in reasons.items():
            changed = copy.deepcopy(self.observation)
            changed.update(status=status, observedDigest=None)
            with self.subTest(status=status):
                self.assertEqual(MODULE.evaluate(self.index, changed, self.now)["reason"], reason)

    def test_requested_or_observed_digest_mismatch_fails(self):
        changed = copy.deepcopy(self.observation)
        changed["requestedDigest"] = "sha256:" + "d" * 64
        self.assertEqual(MODULE.evaluate(self.index, changed, self.now)["reason"], "RequestedDigestMismatch")
        changed = copy.deepcopy(self.observation)
        changed["observedDigest"] = "sha256:" + "d" * 64
        self.assertEqual(MODULE.evaluate(self.index, changed, self.now)["reason"], "ObservedDigestMismatch")

    def test_expired_retention_window_fails(self):
        now = dt.datetime(2027, 1, 1, 0, 0, 1, tzinfo=dt.timezone.utc)
        self.assertEqual(MODULE.evaluate(self.index, self.observation, now)["reason"], "RetentionWindowExpired")

    def test_index_rejects_extra_fields_mutable_source_and_wrong_repository(self):
        for field, value in (("extra", True), ("workflowSourceRevision", "main"), ("repository", "ghcr.io/example/other")):
            changed = copy.deepcopy(self.index)
            changed[field] = value
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "index.json"
                path.write_text(json.dumps(changed))
                with self.subTest(field=field), self.assertRaises(MODULE.ObserverError):
                    MODULE.load_index(path)

    def test_observation_rejects_stale_shape_and_non_utc_time(self):
        changed = copy.deepcopy(self.observation)
        changed["extra"] = True
        with self.assertRaises(MODULE.ObserverError):
            MODULE.validate_observation(changed)
        changed = copy.deepcopy(self.observation)
        changed["observedAtUTC"] = "2026-08-10T20:10:00+02:00"
        with self.assertRaises(MODULE.ObserverError):
            MODULE.validate_observation(changed)

    def test_summary_contains_required_fields_and_no_credential(self):
        result = MODULE.evaluate(self.index, self.observation, self.now)
        summary = MODULE.render_summary(result)
        for phrase in ("OBSERVED-PRESENT", self.index["ociManifestDigest"], self.index["internalBundleDigest"], "NONE-AUTOMATIC"):
            self.assertIn(phrase, summary)
        self.assertNotIn("GHCR_TOKEN", summary)

    def test_registry_challenge_is_exact_and_trusted(self):
        value = 'Bearer realm="https://ghcr.io/token",service="ghcr.io",scope="repository:openkubes/ok141-evidence:pull"'
        self.assertEqual(MODULE._challenge(value), ("https://ghcr.io/token", "ghcr.io", "repository:openkubes/ok141-evidence:pull"))
        for changed in (value.replace("ghcr.io/token", "evil.example/token"), value.replace(":pull", ":push,pull")):
            with self.assertRaises(MODULE.ObserverError):
                MODULE._challenge(changed)

    def test_live_404_is_missing_without_token_output(self):
        def opener(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 404, "not found", {}, None)

        result = MODULE.observe_live(self.index["ociManifestDigest"], "actor", "secret-token", opener)
        self.assertEqual((result["status"], result["reason"]), ("MISSING", "DigestMissing"))
        self.assertNotIn("secret-token", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
