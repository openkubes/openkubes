import copy
import importlib.util
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "observe_recovery_snapshot_v1", ROOT / "observe_recovery_snapshot_v1.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CANDIDATE = ROOT / "recovery-snapshot-candidate-v1.yaml"


class RecoverySnapshotTests(unittest.TestCase):
    def test_candidate_is_bounded_and_not_granted(self):
        candidate = MODULE.verify_candidate(CANDIDATE)
        self.assertFalse(candidate["spec"]["authorization"]["readOnlyGranted"])
        self.assertEqual(
            sum(len(plane["queries"]) for plane in candidate["spec"]["planes"].values()),
            20,
        )

    def test_unbounded_or_secret_query_fails_closed(self):
        candidate = MODULE.read(CANDIDATE)
        for name, mutation in {
            "unbounded": lambda d: d["spec"]["planes"]["ok-infra"]["queries"][-1].pop("labelSelector"),
            "secret": lambda d: d["spec"]["planes"]["ok-mgmt"]["queries"][0].update(rawURI="/api/v1/namespaces/x/secrets/y"),
            "authority": lambda d: d["spec"]["authorization"].update(cleanupAuthorized=True),
        }.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                changed = copy.deepcopy(candidate)
                mutation(changed)
                path = Path(temporary) / "candidate.yaml"
                path.write_text(yaml.safe_dump(changed, sort_keys=False))
                with self.assertRaises(MODULE.SnapshotError):
                    MODULE.verify_candidate(path)

    def test_grant_must_be_current_single_run_and_read_only(self):
        now = datetime.now(timezone.utc)
        grant = MODULE.read(ROOT / "recovery-snapshot-grant-v1.template.yaml")
        grant["spec"].update(
            state="GRANTED",
            candidateDigest=MODULE.sha256(CANDIDATE),
            grantID="synthetic-test-only",
            notBefore=(now - timedelta(minutes=1)).isoformat(),
            notAfter=(now + timedelta(minutes=1)).isoformat(),
            maximumRuns=1,
            readOnlyAuthorized=True,
            credentialUseAuthorized=True,
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "grant.yaml"
            path.write_text(yaml.safe_dump(grant, sort_keys=False))
            MODULE.verify_grant(CANDIDATE, path, now)
            grant["spec"]["mutationAuthorized"] = True
            path.write_text(yaml.safe_dump(grant, sort_keys=False))
            with self.assertRaises(MODULE.SnapshotError):
                MODULE.verify_grant(CANDIDATE, path, now)

    def test_query_retains_metadata_only(self):
        query = {"id": "one", "mode": "exact", "rawURI": "/api/v1/namespaces/x"}
        response = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": "x", "uid": "uid", "resourceVersion": "7"},
            "data": {"forbidden": "payload"},
            "status": {"phase": "Active"},
        }

        def runner(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 0, json.dumps(response), "")

        result = MODULE.run_query(Path("/tmp/kubectl"), Path("/tmp/kubeconfig"), query, runner)
        self.assertEqual(result["objects"][0]["uid"], "uid")
        self.assertNotIn("data", result["objects"][0])
        self.assertNotIn("status", result["objects"][0])

    def test_snapshot_command_requires_explicit_execute(self):
        result = subprocess.run(
            [
                "python3",
                str(ROOT / "observe_recovery_snapshot_v1.py"),
                "snapshot",
                "--candidate",
                str(CANDIDATE),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("requires --execute", result.stderr)


if __name__ == "__main__":
    unittest.main()
