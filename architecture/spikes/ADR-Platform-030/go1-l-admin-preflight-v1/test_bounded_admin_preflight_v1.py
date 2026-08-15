import base64
import copy
import datetime as dt
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("admin_preflight_test", HERE / "bounded_admin_preflight_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Completed:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


class AdminPreflightTests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "go1-l-admin-preflight-candidate-v1.yaml"
        self.candidate = MODULE.load_candidate(self.path)
        self.now = dt.datetime(2026, 8, 13, 15, 0, tzinfo=dt.timezone.utc)

    def assert_rejected(self, changed):
        with self.assertRaises((MODULE.PreflightError, MODULE.V1.HarnessError)):
            MODULE.validate_candidate(changed, self.path)

    def kubeconfig(self, directory: Path):
        ca = b"test-only-ca"
        path = directory / "admin.kubeconfig"
        path.write_text(
            "apiVersion: v1\n"
            "kind: Config\n"
            "current-context: target\n"
            "contexts:\n- name: target\n  context:\n    cluster: target\n    user: admin\n"
            "clusters:\n- name: target\n  cluster:\n"
            "    server: https://192.0.2.10:6443\n"
            f"    certificate-authority-data: {base64.b64encode(ca).decode()}\n"
            "users:\n- name: admin\n  user:\n    token: TEST-ONLY-NOT-REAL\n"
        )
        os.chmod(path, 0o600)
        return path, MODULE.sha_bytes(ca)

    def grant(self, operation, ca_fingerprint):
        target = "ok-infra" if operation == "provider-prerequisites" else "ok-mgmt"
        return {
            "apiVersion": "authorization.openkubes.io/v1alpha1",
            "kind": "ReadOnlyPreflightGrant",
            "spec": {
                "decision": "GO",
                "credentialUseGranted": True,
                "absencePreflightGranted": True,
                "mutationAuthorized": False,
                "operation": operation,
                "targetPlane": target,
                "candidateDigest": MODULE.sha(self.path),
                "expectedServer": "https://192.0.2.10:6443",
                "expectedCAFingerprint": ca_fingerprint,
                "grantID": "ok141-test-only-preflight",
                "singleRun": True,
                "issuedAt": "2026-08-13T14:58:00Z",
                "expiresAt": "2026-08-13T15:10:00Z",
            },
        }

    def test_candidate_and_fixed_plans_reproduce(self):
        MODULE.validate_candidate(self.candidate, self.path)
        expected = {"provider-prerequisites": 3, "capi-lifecycle": 1, "helmchartproxy": 1}
        for operation, count in expected.items():
            plan = MODULE.build_plan(self.candidate, self.path, operation)
            self.assertEqual(plan["queryCount"], count)
            self.assertFalse(plan["credentialUseGranted"])
            self.assertFalse(plan["clusterContacted"])

    def test_source_tampering_fails_closed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["sourceDecision"]["digest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)

    def test_candidate_grant_tampering_fails_closed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["authorization"]["credentialUseGranted"] = True
        self.assert_rejected(changed)

    def test_broad_query_fails_closed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["operations"][0]["queries"][0]["name"] = ""
        self.assert_rejected(changed)

    def test_authority_plane_swap_fails_closed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["operations"][0]["targetPlane"] = "ok-mgmt"
        self.assert_rejected(changed)

    def test_list_or_mutation_transport_fails_closed(self):
        for key in ("listWatchAllowed", "mutationAllowed"):
            changed = copy.deepcopy(self.candidate)
            changed["spec"]["queryTransport"][key] = True
            with self.subTest(key=key):
                self.assert_rejected(changed)

    def test_all_absent_fake_run_passes_without_secret_output(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return Completed()

        with tempfile.TemporaryDirectory() as temp:
            credential, ca = self.kubeconfig(Path(temp))
            result = MODULE.run_absence_preflight(
                self.candidate, self.path, "provider-prerequisites", self.grant("provider-prerequisites", ca), credential, self.now, runner
            )
        self.assertEqual(result["preflightResult"], "PASS-ABSENT")
        self.assertEqual(len(result["observations"]), 3)
        self.assertNotIn("user", result)
        self.assertTrue(all(call[0][3] == "get" for call in calls))

    def test_present_object_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            credential, ca = self.kubeconfig(Path(temp))
            with self.assertRaises(MODULE.PreflightError):
                MODULE.run_absence_preflight(
                    self.candidate, self.path, "capi-lifecycle", self.grant("capi-lifecycle", ca), credential, self.now,
                    runner=lambda *args, **kwargs: Completed(stdout='{"kind":"Namespace"}'),
                )

    def test_query_error_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            credential, ca = self.kubeconfig(Path(temp))
            with self.assertRaises(MODULE.PreflightError):
                MODULE.run_absence_preflight(
                    self.candidate, self.path, "helmchartproxy", self.grant("helmchartproxy", ca), credential, self.now,
                    runner=lambda *args, **kwargs: Completed(returncode=1),
                )

    def test_expired_grant_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            credential, ca = self.kubeconfig(Path(temp))
            grant = self.grant("provider-prerequisites", ca)
            grant["spec"]["expiresAt"] = "2026-08-13T14:59:00Z"
            with self.assertRaises(MODULE.PreflightError):
                MODULE.run_absence_preflight(self.candidate, self.path, "provider-prerequisites", grant, credential, self.now)

    def test_wrong_server_or_ca_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            credential, ca = self.kubeconfig(Path(temp))
            for field in ("expectedServer", "expectedCAFingerprint"):
                grant = self.grant("provider-prerequisites", ca)
                grant["spec"][field] = "wrong"
                with self.subTest(field=field), self.assertRaises(MODULE.PreflightError):
                    MODULE.run_absence_preflight(self.candidate, self.path, "provider-prerequisites", grant, credential, self.now)

    def test_mutating_grant_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            credential, ca = self.kubeconfig(Path(temp))
            grant = self.grant("provider-prerequisites", ca)
            grant["spec"]["mutationAuthorized"] = True
            with self.assertRaises(MODULE.PreflightError):
                MODULE.run_absence_preflight(self.candidate, self.path, "provider-prerequisites", grant, credential, self.now)

    def test_insecure_or_permissive_credential_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            credential, _ = self.kubeconfig(Path(temp))
            os.chmod(credential, 0o644)
            with self.assertRaises(MODULE.PreflightError):
                MODULE.inspect_kubeconfig(credential)

    def test_exec_plugin_or_proxy_kubeconfig_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            credential, _ = self.kubeconfig(Path(temp))
            for mode in ("exec", "proxy"):
                config = yaml.safe_load(credential.read_text())
                if mode == "exec":
                    config["users"][0]["user"] = {"exec": {"command": "forbidden"}}
                else:
                    config["clusters"][0]["cluster"]["proxy-url"] = "https://proxy.invalid"
                credential.write_text(yaml.safe_dump(config, sort_keys=False))
                os.chmod(credential, 0o600)
                with self.subTest(mode=mode), self.assertRaises(MODULE.PreflightError):
                    MODULE.inspect_kubeconfig(credential)
                credential, _ = self.kubeconfig(Path(temp))


if __name__ == "__main__":
    unittest.main()
