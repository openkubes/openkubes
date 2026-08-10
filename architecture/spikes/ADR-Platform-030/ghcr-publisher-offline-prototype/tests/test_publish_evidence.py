import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ok141_publish_evidence_test", HERE / "publish_evidence.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PublishEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "evidence"
        self.root.mkdir()
        (self.root / "result.json").write_text('{"status":"Ready"}\n')
        context = {
            "runId": "123456789",
            "createdAt": "2026-08-10T18:30:02Z",
            "protocolDigest": "sha256:" + "1" * 64,
            "fixtureDigest": "sha256:" + "2" * 64,
            "decisionInputDigest": MODULE.BUNDLE.DECISION_INPUT_DIGEST,
            "targetIdentities": {"workload": {"uid": "test-cluster-uid"}},
            "observedFrom": "2026-08-10T18:30:00Z",
            "observedUntil": "2026-08-10T18:30:01Z",
            "clockSource": "fixture-utc",
            "maximumClockSkewSeconds": 5,
        }
        self.manifest = MODULE.BUNDLE.build(self.root, context)
        self.manifest_path = Path(self.temp.name) / "evidence-bundle.json"
        self.manifest_path.write_text(json.dumps(self.manifest))
        self.transport, self.plan = MODULE.build_transport(self.root, self.manifest_path, "123456789")
        self.oci = "sha256:" + "3" * 64
        self.receipt = MODULE.build_receipt(self.plan, self.oci, self.oci, "https://github.com/openkubes/openkubes/actions/runs/987654321")

    def tearDown(self):
        self.temp.cleanup()

    def test_transport_is_deterministic_and_bundle_bound(self):
        second, plan = MODULE.build_transport(self.root, self.manifest_path, "123456789")
        self.assertEqual(self.transport, second)
        self.assertEqual(self.plan, plan)
        self.assertEqual(self.plan["internalBundleDigest"], self.manifest["spec"]["bundleDigest"])
        self.assertFalse(self.plan["tagAuthoritative"])

    def test_source_run_id_is_exact_and_bound(self):
        for value in ("0", "-1", "123abc", "123456788"):
            with self.subTest(value=value), self.assertRaises((MODULE.PublicationError, MODULE.BUNDLE.EvidenceError)):
                MODULE.build_transport(self.root, self.manifest_path, value)

    def test_changed_evidence_is_rejected_before_transport(self):
        (self.root / "result.json").write_text('{"status":"Changed"}\n')
        with self.assertRaises(MODULE.BUNDLE.EvidenceError):
            MODULE.build_transport(self.root, self.manifest_path, "123456789")

    def test_receipt_verifies_exact_pullback(self):
        result = MODULE.validate_receipt(self.plan, self.receipt, self.transport)
        self.assertEqual(result["status"], "VERIFIED-PULL-BACK")
        self.assertEqual(result["ociManifestDigest"], self.oci)

    def test_tag_is_never_authoritative(self):
        self.assertEqual(self.plan["nonAuthoritativeTag"], "run-123456789")
        self.assertNotIn(self.plan["nonAuthoritativeTag"], self.receipt["pullReference"])
        self.assertEqual(self.receipt["pullReference"], f"{MODULE.REPOSITORY}@{self.oci}")

    def test_changed_pulled_transport_is_rejected(self):
        with self.assertRaises(MODULE.PublicationError):
            MODULE.validate_receipt(self.plan, self.receipt, self.transport + b"tamper")

    def test_wrong_attestation_subject_is_rejected(self):
        changed = copy.deepcopy(self.receipt)
        changed["attestationSubjectDigest"] = "sha256:" + "4" * 64
        with self.assertRaises(MODULE.PublicationError):
            MODULE.validate_receipt(self.plan, changed, self.transport)
        with self.assertRaises(MODULE.PublicationError):
            MODULE.build_receipt(self.plan, self.oci, "sha256:" + "4" * 64, changed["workflowRunURL"])

    def test_wrong_signer_or_run_url_is_rejected(self):
        changed = copy.deepcopy(self.receipt)
        changed["attestationSignerIdentity"] = "https://github.com/other/repo/workflow"
        with self.assertRaises(MODULE.PublicationError):
            MODULE.validate_receipt(self.plan, changed, self.transport)
        changed = copy.deepcopy(self.receipt)
        changed["workflowRunURL"] = "https://example.com/run/1"
        with self.assertRaises(MODULE.PublicationError):
            MODULE.validate_receipt(self.plan, changed, self.transport)

    def test_extra_receipt_or_plan_fields_fail_closed(self):
        changed = copy.deepcopy(self.receipt)
        changed["tag"] = "latest"
        with self.assertRaises(MODULE.PublicationError):
            MODULE.validate_receipt(self.plan, changed, self.transport)
        changed_plan = copy.deepcopy(self.plan)
        changed_plan["writeAllowed"] = True
        with self.assertRaises(MODULE.PublicationError):
            MODULE.validate_receipt(changed_plan, self.receipt, self.transport)


if __name__ == "__main__":
    unittest.main()
