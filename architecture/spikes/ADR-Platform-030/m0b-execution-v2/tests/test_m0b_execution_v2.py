from __future__ import annotations

import copy
import importlib.util
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


VERIFY = load("ok141_verify_m0b_execution_v2_test", HERE / "verify_m0b_execution_v2.py")
EXECUTION = load("ok141_controlled_m0b_execution_v2_test", HERE / "controlled_m0b_execution_v2.py")
READINESS = load("ok141_evaluate_m0b_readiness_v2_test", HERE / "evaluate_m0b_readiness_v2.py")
READINESS_V22 = load("ok141_evaluate_m0b_readiness_v22_test", HERE / "evaluate_m0b_readiness_v2_2.py")


class M0bExecutionV2Tests(unittest.TestCase):
    def test_checkpoint_verifies(self) -> None:
        self.assertEqual(VERIFY.verify(), VERIFY.GRANT_CANDIDATE_DIGEST)

    def test_readiness_candidate_is_read_only(self) -> None:
        candidate, _ = READINESS.verify_candidate(HERE / "m0b-v2-readiness-candidate.yaml")
        self.assertFalse(any(candidate["spec"]["authorization"].values()))

    def test_ungranted_candidate_cannot_execute(self) -> None:
        with self.assertRaises(EXECUTION.ExecutionError):
            EXECUTION.validate_grant(
                HERE / "m0b-v2-installation-grant-candidate.yaml",
                HERE / "m0b-v2-execution-candidate.yaml",
                datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc),
            )

    def test_changed_preflight_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory)
            for path in HERE.iterdir():
                if path.is_file():
                    (copied / path.name).write_bytes(path.read_bytes())
            preflight_path = copied / "m0b-v2-final-live-preflight-v1.yaml"
            preflight = yaml.safe_load(preflight_path.read_text())
            preflight["spec"]["observations"]["cluster"]["existingReviewedTargetIdentities"] = 1
            preflight_path.write_text(yaml.safe_dump(preflight, sort_keys=False))
            with self.assertRaises(VERIFY.VerificationError):
                VERIFY.verify(copied)

    def test_grant_candidate_is_no_go(self) -> None:
        grant = yaml.safe_load((HERE / "m0b-v2-installation-grant-candidate.yaml").read_text())["spec"]
        self.assertEqual(grant["authorization"]["decision"], "NO-GO")
        self.assertIsNone(grant["explicitGrantFields"]["grantID"])
        self.assertIsNone(grant["explicitGrantFields"]["validFrom"])
        self.assertIsNone(grant["explicitGrantFields"]["validUntil"])

    def test_v22_binds_index_and_platform_child_separately(self) -> None:
        candidate, _ = READINESS_V22.verify_candidate(HERE / "m0b-v2-2-readiness-candidate.yaml")
        for image in candidate["spec"]["runtimeImageIdentity"]:
            self.assertNotEqual(image["indexDigest"], image["linuxAmd64ChildManifestDigest"])
        self.assertEqual(candidate["spec"]["nativeDefaultProject"]["riskState"], "PENDING-EXPLICIT-ACCEPTANCE")
        self.assertFalse(any(candidate["spec"]["authorization"].values()))


if __name__ == "__main__":
    unittest.main()
