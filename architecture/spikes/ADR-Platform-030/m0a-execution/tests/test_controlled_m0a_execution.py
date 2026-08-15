from __future__ import annotations

import copy
import importlib.util
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SPEC = importlib.util.spec_from_file_location("controlled_m0a_execution", ROOT / "controlled_m0a_execution.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class ControlledExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidate_path = ROOT / "m0a-execution-candidate-v1.yaml"
        self.candidate = yaml.safe_load(self.candidate_path.read_text())

    def write_yaml(self, value) -> Path:
        handle = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        yaml.safe_dump(value, handle, sort_keys=False)
        handle.close()
        return Path(handle.name)

    def grant(self) -> dict:
        return {
            "apiVersion": "test.openkubes.io/v1alpha1",
            "kind": "CombinedGateGrant",
            "metadata": {"name": "test"},
            "spec": {
                "version": "ok141-m0a-combined-grant/v1",
                "candidateDigest": MODULE.sha(self.candidate_path),
                "authority": "github:arashkaffamanesh",
                "decision": "GO",
                "mutationAuthorized": True,
                "credentialGrant": {"gate": "M0A-C1", "grantID": "credential-test", "granted": True},
                "installationGrant": {"gate": "M0A-I", "grantID": "installation-test", "granted": True},
                "validFrom": "2026-08-11T20:00:00Z",
                "validUntil": "2026-08-11T21:00:00Z",
                "maximumRuns": 1,
                "rollbackGranted": False,
                "targetConvergenceGranted": False,
                "go1Granted": False,
            },
        }

    def test_candidate_verifies_without_authority(self) -> None:
        candidate, _ = MODULE.verify_candidate(self.candidate_path)
        self.assertEqual(candidate["spec"]["authorization"]["decision"], "NO-GO")

    def test_valid_external_grant_verifies(self) -> None:
        path = self.write_yaml(self.grant())
        try:
            grant = MODULE.verify_grant(self.candidate_path, path, datetime(2026, 8, 11, 20, 30, tzinfo=timezone.utc))
            self.assertEqual(grant["decision"], "GO")
        finally:
            path.unlink(missing_ok=True)

    def test_same_grant_id_fails_closed(self) -> None:
        grant = self.grant()
        grant["spec"]["installationGrant"]["grantID"] = "credential-test"
        path = self.write_yaml(grant)
        try:
            with self.assertRaises(MODULE.ExecutionError):
                MODULE.verify_grant(self.candidate_path, path, datetime(2026, 8, 11, 20, 30, tzinfo=timezone.utc))
        finally:
            path.unlink(missing_ok=True)

    def test_expired_grant_fails_closed(self) -> None:
        path = self.write_yaml(self.grant())
        try:
            with self.assertRaises(MODULE.ExecutionError):
                MODULE.verify_grant(self.candidate_path, path, datetime(2026, 8, 11, 22, 0, tzinfo=timezone.utc))
        finally:
            path.unlink(missing_ok=True)

    def test_candidate_mutation_authority_fails_closed(self) -> None:
        candidate = copy.deepcopy(self.candidate)
        candidate["spec"]["authorization"]["mutationAuthorized"] = True
        path = ROOT / ".test-candidate.yaml"
        path.write_text(yaml.safe_dump(candidate, sort_keys=False))
        try:
            with self.assertRaises(MODULE.ExecutionError):
                MODULE.verify_candidate(path)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
