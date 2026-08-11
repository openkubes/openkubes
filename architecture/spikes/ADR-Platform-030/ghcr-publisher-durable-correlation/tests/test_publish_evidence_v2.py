import copy
import importlib.util
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ok141_publish_evidence_v2", ROOT / "publish_evidence_v2.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class DurableCorrelationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.root = base / "evidence"
        self.root.mkdir()
        (self.root / "result.txt").write_text("verified\n")
        context = {
            "runId": "123456789",
            "createdAt": "2026-08-11T10:01:00Z",
            "protocolDigest": "sha256:" + "1" * 64,
            "fixtureDigest": "sha256:" + "2" * 64,
            "decisionInputDigest": MODULE.BUNDLE.DECISION_INPUT_DIGEST,
            "targetIdentities": {"ok-mgmt": {"uid": "test-uid"}},
            "observedFrom": "2026-08-11T10:00:00Z",
            "observedUntil": "2026-08-11T10:01:00Z",
            "clockSource": "offline-test-clock",
            "maximumClockSkewSeconds": 5,
        }
        self.manifest = MODULE.BUNDLE.build(self.root, context)
        self.manifest_path = base / "evidence-bundle.json"
        self.manifest_path.write_text(json.dumps(self.manifest))
        self.source = {
            "id": 123456789,
            "workflow_id": 987654,
            "repository": {"full_name": "openkubes/openkubes"},
            "event": "workflow_dispatch",
            "head_branch": "main",
            "head_sha": "a" * 40,
            "status": "completed",
            "conclusion": "success",
        }
        self.source_path = base / "source-run.json"
        self.source_path.write_text(json.dumps(self.source))

    def tearDown(self):
        self.temp.cleanup()

    def build(self, source=None):
        if source is not None:
            self.source_path.write_text(json.dumps(source))
        return MODULE.build_transport(
            self.root, self.manifest_path, self.source_path, "123456789",
            "987654", "a" * 40, "sha256:" + "1" * 64,
        )

    def test_transport_is_deterministic_and_contains_correlation(self):
        first, plan, correlation = self.build()
        second, second_plan, _ = self.build()
        self.assertEqual(first, second)
        self.assertEqual(plan, second_plan)
        self.assertEqual(plan["sourceCorrelationDigest"], MODULE._digest(MODULE._canonical(correlation)))
        with tarfile.open(fileobj=io.BytesIO(first), mode="r:") as archive:
            self.assertIn("source-run-correlation.json", archive.getnames())
            embedded = json.load(archive.extractfile("source-run-correlation.json"))
        self.assertEqual(embedded, correlation)

    def test_wrong_repository_is_rejected(self):
        changed = copy.deepcopy(self.source)
        changed["repository"]["full_name"] = "someone/fork"
        with self.assertRaises(MODULE.CorrelationError):
            self.build(changed)

    def test_wrong_head_sha_is_rejected(self):
        changed = copy.deepcopy(self.source)
        changed["head_sha"] = "b" * 40
        with self.assertRaises(MODULE.CorrelationError):
            self.build(changed)

    def test_wrong_workflow_id_is_rejected(self):
        changed = copy.deepcopy(self.source)
        changed["workflow_id"] = 1
        with self.assertRaises(MODULE.CorrelationError):
            self.build(changed)

    def test_unsuccessful_run_is_rejected(self):
        changed = copy.deepcopy(self.source)
        changed["conclusion"] = "failure"
        with self.assertRaises(MODULE.CorrelationError):
            self.build(changed)

    def test_protocol_mismatch_is_rejected(self):
        with self.assertRaises(MODULE.CorrelationError):
            MODULE.build_transport(
                self.root, self.manifest_path, self.source_path, "123456789",
                "987654", "a" * 40, "sha256:" + "3" * 64,
            )

    def test_receipt_preserves_correlation_and_verifies_pullback(self):
        transport, plan, _ = self.build()
        oci_digest = "sha256:" + "4" * 64
        receipt = MODULE.build_receipt(
            plan, oci_digest, oci_digest,
            "https://github.com/openkubes/openkubes/actions/runs/222222222",
        )
        result = MODULE.validate_receipt(plan, receipt, transport)
        self.assertEqual(result["sourceCorrelationDigest"], plan["sourceCorrelationDigest"])
        self.assertEqual(result["status"], "VERIFIED-PULL-BACK-WITH-SOURCE-CORRELATION")

    def test_receipt_tampering_is_rejected(self):
        transport, plan, _ = self.build()
        oci_digest = "sha256:" + "4" * 64
        receipt = MODULE.build_receipt(
            plan, oci_digest, oci_digest,
            "https://github.com/openkubes/openkubes/actions/runs/222222222",
        )
        changed = copy.deepcopy(receipt)
        changed["sourceHeadSHA"] = "b" * 40
        with self.assertRaises(MODULE.CorrelationError):
            MODULE.validate_receipt(plan, changed, transport)

    def test_changed_pullback_is_rejected(self):
        transport, plan, _ = self.build()
        oci_digest = "sha256:" + "4" * 64
        receipt = MODULE.build_receipt(
            plan, oci_digest, oci_digest,
            "https://github.com/openkubes/openkubes/actions/runs/222222222",
        )
        with self.assertRaises(MODULE.CorrelationError):
            MODULE.validate_receipt(plan, receipt, transport + b"tamper")


if __name__ == "__main__":
    unittest.main(verbosity=2)
