import copy
import importlib.util
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "installation_closure_verify_test", HERE / "verify_installation_closure.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class InstallationClosureTests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "installation-closure-v1.yaml"
        self.matrix = MODULE.V1.read_yaml_or_json(self.path)

    def assert_rejected(self, changed):
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_matrix_and_sources_verify(self):
        digest = MODULE.validate(self.matrix, self.path)
        self.assertTrue(digest.startswith("sha256:"))

    def test_mutation_or_grant_fails_closed(self):
        for field in (
            "mutationAuthorized",
            "m0aInstallationGranted",
            "m0bInstallationGranted",
            "go1Granted",
        ):
            changed = copy.deepcopy(self.matrix)
            changed["spec"]["authorization"][field] = True
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_source_digest_tampering_fails_closed(self):
        for source in ("m0aInstallation", "m0bInstallation"):
            changed = copy.deepcopy(self.matrix)
            changed["spec"]["sources"][source]["digest"] = "sha256:" + "0" * 64
            with self.subTest(source=source):
                self.assert_rejected(changed)

    def test_source_blocker_cannot_be_missing(self):
        changed = copy.deepcopy(self.matrix)
        changed["spec"]["blockers"].pop()
        self.assert_rejected(changed)

    def test_source_blocker_cannot_move_between_gates(self):
        changed = copy.deepcopy(self.matrix)
        changed["spec"]["blockers"][0]["gate"] = "M0B-I"
        self.assert_rejected(changed)

    def test_atomic_obligation_cannot_be_missing(self):
        changed = copy.deepcopy(self.matrix)
        blocker = next(item for item in changed["spec"]["blockers"] if item["id"] == "M0AI-INSTALLER-IDENTITY")
        blocker["obligations"].pop()
        self.assert_rejected(changed)

    def test_atomic_obligation_cannot_move_between_blockers(self):
        changed = copy.deepcopy(self.matrix)
        source = next(item for item in changed["spec"]["blockers"] if item["id"] == "M0AI-INSTALLER-IDENTITY")
        target = next(item for item in changed["spec"]["blockers"] if item["id"] == "M0AI-EXACT-OBJECT-SUBMISSION")
        target["obligations"].append(source["obligations"].pop())
        self.assert_rejected(changed)

    def test_class_status_mapping_cannot_change(self):
        changed = copy.deepcopy(self.matrix)
        changed["spec"]["classes"]["OFFLINE-CLOSABLE"]["requiredStatus"] = "CLOSED"
        self.assert_rejected(changed)

    def test_obligation_cannot_be_preclosed(self):
        changed = copy.deepcopy(self.matrix)
        changed["spec"]["blockers"][0]["obligations"][0]["status"] = "CLOSED"
        self.assert_rejected(changed)

    def test_live_or_mutating_obligation_cannot_be_reclassified_offline(self):
        for obligation_id in ("M0AI-BASELINE-LIVE", "M0AI-INSTALLER-CREDENTIAL"):
            changed = copy.deepcopy(self.matrix)
            obligation = next(
                obligation
                for blocker in changed["spec"]["blockers"]
                for obligation in blocker["obligations"]
                if obligation["id"] == obligation_id
            )
            obligation["class"] = "OFFLINE-CLOSABLE"
            obligation["status"] = "OPEN-READ-ONLY"
            with self.subTest(obligation=obligation_id):
                self.assert_rejected(changed)

    def test_summary_cannot_overstate_closure(self):
        changed = copy.deepcopy(self.matrix)
        changed["spec"]["summary"]["byClass"]["OFFLINE-CLOSABLE"] = 10
        self.assert_rejected(changed)

    def test_next_candidates_must_equal_offline_set(self):
        changed = copy.deepcopy(self.matrix)
        changed["spec"]["nextReadOnlyCandidates"].pop()
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.matrix)
        changed["spec"]["nextReadOnlyCandidates"][0] = "M0AI-BASELINE-LIVE"
        self.assert_rejected(changed)

    def test_safety_rules_cannot_authorize_repair(self):
        changed = copy.deepcopy(self.matrix)
        changed["spec"]["rules"] = [
            rule for rule in changed["spec"]["rules"] if "may not create" not in rule
        ]
        self.assert_rejected(changed)


if __name__ == "__main__":
    unittest.main()
