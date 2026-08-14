import copy
import datetime as dt
import importlib.util
import tempfile
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("observe_recovery_r2_test", HERE / "observe_recovery_r2_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
TEMPLATE = HERE / "recovery-r2-candidate-v1.template.yaml"


class RecoveryR2Tests(unittest.TestCase):
    def write(self, directory, name, value):
        path = Path(directory) / name
        path.write_text(yaml.safe_dump(value, sort_keys=False))
        return path

    def result(self, query_id, outcome):
        return {"id": query_id, "outcome": outcome, "objects": []}

    def planes(self):
        return {
            "ok-mgmt": [self.result(item, "ABSENT") for item in sorted(MODULE.MGMT_ABSENT)]
            + [self.result(item, "API_NOT_SERVED") for item in sorted(MODULE.MGMT_API_NOT_SERVED)],
            "ok-infra": [self.result(item, "PRESENT") for item in sorted(MODULE.INFRA_PRESENT)]
            + [self.result(item, "ABSENT") for item in sorted(MODULE.INFRA_ABSENT)],
        }

    def candidate(self):
        value = MODULE.V1.read(TEMPLATE)
        value["metadata"]["name"] = "ok141-go1-l-recovery-r2-test"
        value["spec"]["state"] = "READY-FOR-EXPLICIT-READ-ONLY-GRANT"
        value["spec"]["predecessor"].update(
            {
                "privateRuntimeBindingDigest": "sha256:" + "1" * 64,
                "r1EvidenceDigest": "sha256:" + "2" * 64,
                "r1GrantID": "test-r1-grant",
                "r1State": "ALL-DELETES-ACCEPTED",
            }
        )
        value["spec"]["tool"]["executorDigest"] = MODULE.V1.sha256(HERE / "observe_recovery_r2_v1.py")
        return value

    def grant(self, candidate_path):
        return {
            "apiVersion": "authorization.openkubes.io/v1alpha1",
            "kind": "GO1LRecoveryR2Grant",
            "metadata": {"name": "test", "ticket": "OK-141"},
            "spec": {
                "state": "GRANTED",
                "candidateDigest": MODULE.V1.sha256(candidate_path),
                "grantID": "test-r2",
                "notBefore": "2026-08-14T09:00:00Z",
                "notAfter": "2026-08-14T09:20:00Z",
                "maximumRuns": 1,
                "consumed": False,
                "outputPath": "/private/tmp/ok141-go1-l-recovery-r2-v1-evidence.json",
                "readOnlyAuthorized": True,
                "credentialUseAuthorized": True,
                "mutationAuthorized": False,
                "cleanupAuthorized": False,
                "retryAuthorized": False,
                "secretReadAuthorized": False,
                "r3Authorized": False,
                "recreateAuthorized": False,
                "go1LAuthorized": False,
                "go1Authorized": False,
                "failureInjectionAuthorized": False,
            },
        }

    def test_candidate_is_bounded_reproducible_and_not_authorized(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write(temporary, "candidate.yaml", self.candidate())
            candidate = MODULE.verify_candidate(path)
            self.assertEqual(candidate["spec"]["polling"]["maximumDurationSeconds"], 600)
            self.assertFalse(any(candidate["spec"]["authorization"].values()))

    def test_predecessor_query_polling_or_authority_tampering_fails_closed(self):
        for mutation in ("predecessor", "query", "polling", "authority"):
            changed = copy.deepcopy(self.candidate())
            if mutation == "predecessor":
                changed["spec"]["predecessor"]["r1State"] = "DELETE-NOT-ACCEPTED"
            elif mutation == "query":
                changed["spec"]["planes"]["ok-infra"]["queries"][0]["rawURI"] += "-wrong"
            elif mutation == "polling":
                changed["spec"]["polling"]["maximumIterations"] = 61
            else:
                changed["spec"]["authorization"]["r3Authorized"] = True
            with tempfile.TemporaryDirectory() as temporary:
                with self.assertRaises(MODULE.ObservationError):
                    MODULE.verify_candidate(self.write(temporary, "candidate.yaml", changed))

    def test_closure_evaluation_passes_only_exact_expected_state(self):
        self.assertEqual(MODULE.evaluate(self.planes()), "PASS-R2-CLEAN")
        changed = self.planes()
        changed["ok-mgmt"][0]["outcome"] = "PRESENT"
        self.assertEqual(MODULE.evaluate(changed), "BLOCKED-MANAGEMENT-STATE-REMAINS")
        changed = self.planes()
        changed["ok-infra"][0]["outcome"] = "ABSENT"
        self.assertEqual(MODULE.evaluate(changed), "FAIL-INFRA-PREREQUISITE-STATE")

    def test_grant_is_current_single_run_read_only_and_excludes_r3(self):
        with tempfile.TemporaryDirectory() as temporary:
            candidate_path = self.write(temporary, "candidate.yaml", self.candidate())
            path = self.write(temporary, "grant.yaml", self.grant(candidate_path))
            MODULE.verify_grant(candidate_path, path, dt.datetime(2026, 8, 14, 9, 10, tzinfo=dt.timezone.utc))
            changed = self.grant(candidate_path)
            changed["spec"]["r3Authorized"] = True
            bad = self.write(temporary, "bad.yaml", changed)
            with self.assertRaises(MODULE.ObservationError):
                MODULE.verify_grant(candidate_path, bad, dt.datetime(2026, 8, 14, 9, 10, tzinfo=dt.timezone.utc))


if __name__ == "__main__":
    unittest.main()
