import copy
import importlib.util
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("live_closure_test", HERE / "verify_live_closure.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class LiveClosureTests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "live-closure-results-v1.yaml"
        self.document = MODULE.V1.read_yaml_or_json(self.path)

    def test_complete_live_evaluation_verifies(self):
        self.assertTrue(MODULE.validate(self.document, self.path).startswith("sha256:"))

    def test_grant_or_mutation_is_rejected(self):
        for field, value in (
            ("decision", "GO"),
            ("mutationAuthorized", True),
            ("m0aInstallationGranted", True),
            ("m0bInstallationGranted", True),
            ("go1Granted", True),
        ):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.document)
                changed["spec"]["authorization"][field] = value
                with self.assertRaises(MODULE.OBSERVER.ObservationError):
                    MODULE.validate(changed, self.path)

    def test_missing_live_obligation_is_rejected(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["results"].pop()
        with self.assertRaises((MODULE.OBSERVER.ObservationError, ValueError)):
            MODULE.validate(changed, self.path)

    def test_partial_compatibility_cannot_be_overclaimed(self):
        changed = copy.deepcopy(self.document)
        result = next(item for item in changed["spec"]["results"] if item["id"] == "M0AI-COMPATIBILITY-CURRENT-TUPLE")
        result["result"] = "OBSERVED-REPEATABLE-PREFLIGHT"
        with self.assertRaises(MODULE.OBSERVER.ObservationError):
            MODULE.validate(changed, self.path)

    def test_missing_recovery_cannot_be_claimed_resolved(self):
        changed = copy.deepcopy(self.document)
        result = next(item for item in changed["spec"]["results"] if item["id"] == "M0BI-RECOVERY-EVIDENCE-LIVE")
        result["result"] = "OBSERVED-REPEATABLE-PREFLIGHT"
        with self.assertRaises(MODULE.OBSERVER.ObservationError):
            MODULE.validate(changed, self.path)

    def test_single_control_plane_cannot_claim_production_ha(self):
        changed = MODULE.V1.read_yaml_or_json(HERE / "evidence" / "ok-shared-live-v1.yaml")
        changed["spec"]["topology"]["productionHAClaimAllowed"] = True
        original = MODULE.V1.read_yaml_or_json

        def loader(path):
            if Path(path).resolve() == (HERE / "evidence" / "ok-shared-live-v1.yaml").resolve():
                return changed
            return original(path)

        MODULE.V1.read_yaml_or_json = loader
        try:
            with self.assertRaises(MODULE.OBSERVER.ObservationError):
                MODULE.validate(self.document, self.path)
        finally:
            MODULE.V1.read_yaml_or_json = original

    def test_source_blocker_cannot_be_closed(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["summary"]["sourceBlockersClosed"] = 1
        with self.assertRaises(MODULE.OBSERVER.ObservationError):
            MODULE.validate(changed, self.path)

    def test_artifact_digest_tampering_is_rejected(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["artifacts"]["management"]["digest"] = "sha256:" + "0" * 64
        with self.assertRaises(MODULE.OBSERVER.ObservationError):
            MODULE.validate(changed, self.path)


if __name__ == "__main__":
    unittest.main()
