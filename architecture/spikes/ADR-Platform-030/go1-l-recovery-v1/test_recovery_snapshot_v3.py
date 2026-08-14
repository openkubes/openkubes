import copy
import datetime as dt
import importlib.util
import tempfile
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("observe_recovery_snapshot_v3_test", HERE / "observe_recovery_snapshot_v3.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
CANDIDATE = HERE / "recovery-snapshot-candidate-v3.yaml"
V2_CANDIDATE = HERE / "recovery-snapshot-candidate-v2.yaml"


class RecoverySnapshotV3Tests(unittest.TestCase):
    def write_yaml(self, directory, name, value):
        path = Path(directory) / name
        path.write_text(yaml.safe_dump(value, sort_keys=False))
        return path

    def grant(self):
        value = MODULE.V1.read(HERE / "recovery-snapshot-grant-v3.template.yaml")
        value["spec"].update(
            {
                "state": "GRANTED",
                "candidateDigest": MODULE.V1.sha256(CANDIDATE),
                "grantID": "ok141-r0-v3-test",
                "notBefore": "2026-08-14T08:00:00Z",
                "notAfter": "2026-08-14T08:10:00Z",
                "maximumRuns": 1,
                "readOnlyAuthorized": True,
                "credentialUseAuthorized": True,
            }
        )
        return value

    def test_v3_is_reproducible_additive_and_v2_remains_valid(self):
        candidate = MODULE.verify_candidate(CANDIDATE)
        MODULE.V2.verify_candidate(V2_CANDIDATE)
        self.assertEqual(candidate["spec"]["supersedes"]["candidateDigest"], MODULE.V2_CANDIDATE_DIGEST)
        self.assertNotEqual(
            candidate["spec"]["evidence"]["outputPath"],
            MODULE.V2.V1.read(V2_CANDIDATE)["spec"]["evidence"]["outputPath"],
        )
        self.assertEqual(
            sum(len(plane["queries"]) for plane in candidate["spec"]["planes"].values()), 20
        )

    def test_history_or_authority_tampering_fails_closed(self):
        for mutation in ("history", "authority"):
            changed = copy.deepcopy(MODULE.V1.read(CANDIDATE))
            if mutation == "history":
                changed["spec"]["supersedes"]["privateEvidenceDigest"] = "sha256:" + "0" * 64
            else:
                changed["spec"]["authorization"]["cleanupAuthorized"] = True
            with tempfile.TemporaryDirectory() as temporary:
                path = self.write_yaml(temporary, "candidate.yaml", changed)
                with self.assertRaises(MODULE.SnapshotError):
                    MODULE.verify_candidate(path)

    def test_single_run_bounded_grant_is_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_yaml(temporary, "grant.yaml", self.grant())
            verified = MODULE.verify_grant(
                CANDIDATE, path, dt.datetime(2026, 8, 14, 8, 5, tzinfo=dt.timezone.utc)
            )
            self.assertEqual(verified["spec"]["maximumRuns"], 1)

            changed = self.grant()
            changed["spec"]["retryAuthorized"] = True
            changed_path = self.write_yaml(temporary, "bad-grant.yaml", changed)
            with self.assertRaises(MODULE.SnapshotError):
                MODULE.verify_grant(
                    CANDIDATE,
                    changed_path,
                    dt.datetime(2026, 8, 14, 8, 5, tzinfo=dt.timezone.utc),
                )


if __name__ == "__main__":
    unittest.main()
