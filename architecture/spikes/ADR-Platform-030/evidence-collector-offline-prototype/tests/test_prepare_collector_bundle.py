import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ok141_prepare_collector", ROOT / "prepare_collector_bundle.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class CollectorBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.evidence = base / "evidence"
        self.evidence.mkdir()
        (self.evidence / "status.json").write_text('{"ready":true}\n')
        self.context = {
            "protocolDigest": "sha256:" + "1" * 64,
            "fixtureDigest": "sha256:" + "2" * 64,
            "decisionInputDigest": MODULE.BUNDLE.DECISION_INPUT_DIGEST,
            "targetIdentities": {"ok-mgmt": {"uid": "test-uid"}},
            "observedFrom": "2026-08-11T10:00:00Z",
            "observedUntil": "2026-08-11T10:01:00Z",
            "clockSource": "offline-test-clock",
            "maximumClockSkewSeconds": 5,
        }
        self.context_path = base / "context.json"
        self.write_context(self.context)

    def tearDown(self):
        self.temp.cleanup()

    def write_context(self, context):
        self.context_path.write_text(json.dumps(context, sort_keys=True, separators=(",", ":")) + "\n")
        self.context_digest = "sha256:" + hashlib.sha256(self.context_path.read_bytes()).hexdigest()

    def prepare(self, **changed):
        values = {
            "evidence_root": self.evidence,
            "context_path": self.context_path,
            "expected_context_digest": self.context_digest,
            "expected_protocol_digest": "sha256:" + "1" * 64,
            "expected_fixture_digest": "sha256:" + "2" * 64,
            "run_id": "123456789",
            "created_at": "2026-08-11T10:02:00Z",
            "intake_commit": "a" * 40,
            "intake_path": "architecture/spikes/ADR-Platform-030/evidence/intake/ok141-test",
        }
        values.update(changed)
        return MODULE.prepare(**values)

    def test_bundle_is_built_and_bound_to_run(self):
        manifest, receipt = self.prepare()
        self.assertEqual(manifest["spec"]["runId"], "123456789")
        self.assertEqual(receipt["bundleDigest"], manifest["spec"]["bundleDigest"])
        self.assertEqual(receipt["intakeCommit"], "a" * 40)
        self.assertIn("collector-source.json", [item["path"] for item in manifest["spec"]["artifacts"]])
        self.assertFalse(receipt["publicationAuthorized"])

    def test_changed_context_is_rejected(self):
        changed = copy.deepcopy(self.context)
        changed["clockSource"] = "changed"
        self.context_path.write_text(json.dumps(changed))
        with self.assertRaises(MODULE.CollectorError):
            self.prepare()

    def test_wrong_protocol_is_rejected(self):
        with self.assertRaises(MODULE.CollectorError):
            self.prepare(expected_protocol_digest="sha256:" + "3" * 64)

    def test_wrong_fixture_is_rejected(self):
        with self.assertRaises(MODULE.CollectorError):
            self.prepare(expected_fixture_digest="sha256:" + "3" * 64)

    def test_bad_run_id_is_rejected(self):
        with self.assertRaises(MODULE.CollectorError):
            self.prepare(run_id="latest")

    def test_unreviewed_intake_path_is_rejected(self):
        with self.assertRaises(MODULE.CollectorError):
            self.prepare(intake_path="/tmp/evidence")

    def test_secret_evidence_is_rejected(self):
        (self.evidence / "secret.yaml").write_text("apiVersion: v1\nkind: Secret\n")
        with self.assertRaises(MODULE.BUNDLE.EvidenceError):
            self.prepare()


if __name__ == "__main__":
    unittest.main(verbosity=2)
