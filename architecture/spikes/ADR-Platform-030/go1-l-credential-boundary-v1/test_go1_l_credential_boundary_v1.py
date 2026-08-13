import copy
import importlib.util
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("credential_boundary_test", HERE / "verify_go1_l_credential_boundary_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CredentialBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.boundary = MODULE.V1.read_yaml_or_json(MODULE.BOUNDARY)

    def assert_rejected(self, changed):
        with self.assertRaises(MODULE.BoundaryError):
            MODULE.validate(changed)

    def test_boundary_reproduces_without_authority(self):
        self.assertTrue(MODULE.validate(self.boundary).startswith("sha256:"))

    def test_native_name_enforcement_overclaim_fails(self):
        changed = copy.deepcopy(self.boundary)
        changed["spec"]["authoritativeFinding"]["nativeRBACCanEnforceExactObjectNamesOnCreate"] = True
        self.assert_rejected(changed)

    def test_operation_content_enforcement_overclaim_fails(self):
        changed = copy.deepcopy(self.boundary)
        changed["spec"]["operationExposure"][0]["exactContentEnforcedByNativeRBAC"] = True
        self.assert_rejected(changed)

    def test_authority_plane_swap_fails(self):
        changed = copy.deepcopy(self.boundary)
        changed["spec"]["operationExposure"][0]["targetPlane"] = "ok-mgmt"
        self.assert_rejected(changed)

    def test_model_preselection_fails(self):
        changed = copy.deepcopy(self.boundary)
        changed["spec"]["decision"]["selectedModel"] = "DEV-ADMIN-CREATE"
        self.assert_rejected(changed)

    def test_any_grant_fails(self):
        for key in ("credentialIssuanceAuthorized", "admissionInstallationAuthorized", "administratorCredentialAuthorized", "go1LAuthorized"):
            changed = copy.deepcopy(self.boundary)
            changed["spec"]["decision"][key] = True
            with self.subTest(key=key):
                self.assert_rejected(changed)

    def test_reconciler_claim_fails(self):
        changed = copy.deepcopy(self.boundary)
        changed["spec"]["conclusions"]["newOpenKubesReconcilerRequired"] = True
        self.assert_rejected(changed)


if __name__ == "__main__":
    unittest.main()
