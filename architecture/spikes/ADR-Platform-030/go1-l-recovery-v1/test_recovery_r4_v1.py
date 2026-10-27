import copy
import datetime as dt
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("observe_recovery_r4_test", HERE / "observe_recovery_r4_v1.py")
R4 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = R4
assert SPEC.loader is not None
SPEC.loader.exec_module(R4)
TEMPLATE = HERE / "recovery-r4-candidate-v1.template.yaml"


class RecoveryR4Tests(unittest.TestCase):
    def write(self, directory, name, value, mode=None):
        path = Path(directory) / name
        path.write_text(yaml.safe_dump(value, sort_keys=False))
        if mode is not None:
            path.chmod(mode)
        return path

    def candidate(self):
        value = R4.V1.read(TEMPLATE)
        value["metadata"]["name"] = "ok141-r4-test"
        value["spec"]["state"] = "READY-FOR-EXPLICIT-READ-ONLY-GRANT"
        value["spec"]["predecessor"].update(
            {
                "privateRuntimeBindingDigest": "sha256:" + "1" * 64,
                "r3EvidenceDigest": "sha256:" + "2" * 64,
                "r3GrantID": "test-r3",
                "r3State": "ALL-DELETES-ACCEPTED",
            }
        )
        return value

    def grant(self, candidate_path):
        return {
            "apiVersion": "authorization.openkubes.io/v1alpha1",
            "kind": "GO1LRecoveryR4Grant",
            "metadata": {"name": "test-r4", "ticket": "OK-141"},
            "spec": {
                "state": "GRANTED",
                "candidateDigest": R4.V1.sha256(candidate_path),
                "grantID": "test-r4",
                "notBefore": "2026-08-14T09:30:00Z",
                "notAfter": "2026-08-14T09:45:00Z",
                "maximumRuns": 1,
                "consumed": False,
                "outputPath": "/private/tmp/ok141-go1-l-recovery-r4-v1-evidence.json",
                "readOnlyAuthorized": True,
                "credentialUseAuthorized": True,
                "mutationAuthorized": False,
                "cleanupAuthorized": False,
                "retryAuthorized": False,
                "secretReadAuthorized": False,
                "recreateAuthorized": False,
                "go1LAuthorized": False,
                "go1Authorized": False,
                "failureInjectionAuthorized": False,
            },
        }

    def planes(self, infra_present=None):
        infra_present = infra_present or set()
        return {
            "ok-mgmt": [
                {"id": item, "outcome": "ABSENT"} for item in sorted(R4.MGMT_ABSENT)
            ] + [
                {"id": item, "outcome": "API_NOT_SERVED"} for item in sorted(R4.MGMT_API_NOT_SERVED)
            ],
            "ok-infra": [
                {"id": item, "outcome": "PRESENT" if item in infra_present else "ABSENT"}
                for item in sorted(R4.INFRA_ABSENT)
            ],
        }

    def test_candidate_is_exact_and_non_authorizing(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write(temporary, "candidate.yaml", self.candidate())
            candidate = R4.verify_candidate(path)
            self.assertFalse(any(candidate["spec"]["authorization"].values()))
            self.assertEqual(candidate["spec"]["polling"]["targetPlane"], "ok-infra")
            self.assertEqual(candidate["spec"]["polling"]["targetQueryID"], "infra-namespace")

    def test_only_fully_absent_state_passes(self):
        self.assertEqual(R4.evaluate(self.planes()), "PASS-R4-CLEAN-BASELINE")
        for item in R4.INFRA_ABSENT:
            self.assertEqual(R4.evaluate(self.planes({item})), "BLOCKED-INFRA-STATE-REMAINS")

    def test_wrong_query_set_or_api_boundary_fails(self):
        missing = self.planes()
        missing["ok-infra"].pop()
        self.assertEqual(R4.evaluate(missing), "FAIL-QUERY-SET")
        boundary = self.planes()
        boundary["ok-mgmt"][0]["outcome"] = "PRESENT"
        self.assertEqual(R4.evaluate(boundary), "BLOCKED-MANAGEMENT-STATE-REMAINS")

    def test_candidate_tampering_fails_closed(self):
        for mutation in ("query", "predecessor", "authority"):
            value = copy.deepcopy(self.candidate())
            if mutation == "query":
                value["spec"]["planes"]["ok-infra"]["queries"].reverse()
            elif mutation == "predecessor":
                value["spec"]["predecessor"]["r3State"] = "UNKNOWN"
            else:
                value["spec"]["authorization"]["mutationAuthorized"] = True
            with tempfile.TemporaryDirectory() as temporary:
                path = self.write(temporary, "candidate.yaml", value)
                with self.assertRaises(R4.ObservationError):
                    R4.verify_candidate(path)

    def test_grant_is_current_single_run_and_read_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            candidate_path = self.write(temporary, "candidate.yaml", self.candidate())
            grant = self.grant(candidate_path)
            grant_path = self.write(temporary, "grant.yaml", grant)
            now = dt.datetime(2026, 8, 14, 9, 35, tzinfo=dt.timezone.utc)
            R4.verify_grant(candidate_path, grant_path, now)
            for claim in ("retryAuthorized", "mutationAuthorized", "recreateAuthorized"):
                changed = copy.deepcopy(grant)
                changed["spec"][claim] = True
                changed_path = self.write(temporary, f"{claim}.yaml", changed)
                with self.assertRaises(R4.ObservationError):
                    R4.verify_grant(candidate_path, changed_path, now)


if __name__ == "__main__":
    unittest.main()
