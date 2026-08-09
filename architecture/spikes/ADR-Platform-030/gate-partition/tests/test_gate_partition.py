import copy
import importlib.util
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "gate_partition_verify_test", HERE / "verify_gate_partition.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GatePartitionTests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "gate-partition-v1.yaml"
        self.partition = MODULE.V1.read_yaml_or_json(self.path)

    def test_partition_reproduces_bound_digest(self):
        digest = MODULE.validate(self.partition, self.path)
        self.assertTrue(digest.startswith("sha256:"))

    def test_mutation_or_go_authority_fails_closed(self):
        for field in (
            "mutationAuthorized",
            "m0aInstallationGranted",
            "m0bInstallationGranted",
            "go1Granted",
        ):
            changed = copy.deepcopy(self.partition)
            changed["spec"]["authorization"][field] = True
            with self.subTest(field=field), self.assertRaises(MODULE.V1.HarnessError):
                MODULE.validate(changed, self.path)

    def test_missing_pre_go_requirement_fails_closed(self):
        changed = copy.deepcopy(self.partition)
        changed["spec"]["preGoRequirements"].pop()
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_runtime_obligation_cannot_be_preclosed(self):
        changed = copy.deepcopy(self.partition)
        changed["spec"]["runtimeObligations"][0]["status"] = "CLOSED"
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_runtime_obligation_cannot_move_to_g1(self):
        changed = copy.deepcopy(self.partition)
        changed["spec"]["runtimeObligations"][0]["phase"] = "G1"
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_deferred_scenario_cannot_enter_go1(self):
        changed = copy.deepcopy(self.partition)
        changed["spec"]["deferredScenarios"][0]["includedInGO1"] = True
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_source_blocker_coverage_omission_fails_closed(self):
        changed = copy.deepcopy(self.partition)
        for collection in ("preGoRequirements", "runtimeObligations"):
            for item in changed["spec"][collection]:
                item["sourceBlockers"] = [
                    blocker for blocker in item["sourceBlockers"]
                    if blocker != "M0B-RUNTIME-CAPABILITY"
                ]
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_split_blocker_cannot_be_collapsed_to_pre_go(self):
        changed = copy.deepcopy(self.partition)
        for item in changed["spec"]["runtimeObligations"]:
            item["sourceBlockers"] = [
                blocker for blocker in item["sourceBlockers"]
                if blocker != "M0B-REGISTRATION"
            ]
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_installation_gate_cannot_claim_target_convergence(self):
        changed = copy.deepcopy(self.partition)
        changed["spec"]["installationGates"][0]["mayAuthorizeTargetConvergence"] = True
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_source_protocol_tampering_fails_closed(self):
        changed = copy.deepcopy(self.partition)
        changed["spec"]["sourceProtocol"]["draftDigest"] = "sha256:" + "0" * 64
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)


if __name__ == "__main__":
    unittest.main()
