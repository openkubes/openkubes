import copy
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "bounded_installer_test", HERE / "bounded_installer.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class BoundedInstallerTests(unittest.TestCase):
    def setUp(self):
        self.m0a_path = HERE.parent / "m0a-installation" / "m0a-installation-v1.yaml"
        self.m0b_path = HERE.parent / "m0b-installation" / "m0b-installation-v1.yaml"
        self.m0a = MODULE.V1.read_yaml_or_json(self.m0a_path)
        self.m0b = MODULE.V1.read_yaml_or_json(self.m0b_path)

    def test_command_surface_is_semantic_and_closed(self):
        parser = MODULE.build_parser()
        subparser_action = next(action for action in parser._actions if action.dest == "command")
        self.assertEqual(set(subparser_action.choices), {"materialize", "verify", "apply", "evidence"})

    def test_m0a_exact_object_set_verifies(self):
        reviewed = MODULE.verify_reviewed_object_set(self.m0a, self.m0a_path)
        self.assertEqual(reviewed.gate, "M0A-I")
        self.assertEqual(len(reviewed.documents), 19)
        self.assertEqual(reviewed.semantic_digest, self.m0a["spec"]["source"]["semanticDigest"])

    def test_current_no_go_protocol_refuses_apply(self):
        reviewed = MODULE.verify_reviewed_object_set(self.m0a, self.m0a_path)
        with self.assertRaises(MODULE.InstallerError):
            MODULE._authorization_plan(self.m0a, self.m0a_path, reviewed)

    def test_wrong_target_plane_is_rejected(self):
        changed = copy.deepcopy(self.m0a)
        changed["spec"]["submission"]["targetPlane"] = "ok-infra"
        with self.assertRaises(MODULE.InstallerError):
            MODULE.verify_reviewed_object_set(changed, self.m0a_path)

    def test_wrong_manifest_is_rejected(self):
        changed = copy.deepcopy(self.m0a)
        changed["spec"]["source"]["manifestPath"] = "../m0a-v2/helmchartproxy-v4-candidate.yaml"
        with self.assertRaises(MODULE.InstallerError):
            MODULE.verify_reviewed_object_set(changed, self.m0a_path)

    def test_materialization_rejects_unlocked_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(MODULE.InstallerError):
                MODULE.materialize_m0b(
                    self.m0b,
                    self.m0b_path,
                    Path(directory),
                    fetch=lambda _url: b"apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: tampered\n",
                )

    def test_authorized_plan_has_fixed_no_shell_transport(self):
        reviewed = MODULE.verify_reviewed_object_set(self.m0a, self.m0a_path)
        changed = copy.deepcopy(self.m0a)
        authorization = changed["spec"]["authorization"]
        authorization.update({
            "decision": "GO",
            "mutationAuthorized": True,
            "m0aInstallationGranted": True,
            "authorizedProtocolDigest": MODULE.V1.sha256_bytes(self.m0a_path.read_bytes()),
            "grantID": "synthetic-test-only",
            "authority": "synthetic-test-only",
            "decidedAt": "2026-08-10T00:00:00Z",
        })
        changed["spec"]["submission"]["enabled"] = True
        changed["spec"]["target"]["kubeContextIdentity"] = "synthetic-context"
        for requirement in changed["spec"]["preInstallationRequirements"]:
            requirement["status"] = "CLOSED"
        next(item for item in changed["spec"]["phases"] if item["id"] == "M0AI-G1")["enabled"] = True
        plan = MODULE._authorization_plan(changed, self.m0a_path, reviewed)
        self.assertEqual(
            plan["command"],
            ["kubectl", "--context", "synthetic-context", "apply", "--server-side", "--field-manager", "openkubes-ok141-m0ai", "--filename", "-"],
        )
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, b"", b"")

        MODULE.execute_apply(plan, reviewed.payload, runner=runner)
        self.assertEqual(calls[0][0], plan["command"])
        self.assertEqual(calls[0][1]["input"], reviewed.payload)
        self.assertTrue(calls[0][1]["check"])
        self.assertNotIsInstance(calls[0][0], str)

    def test_apply_transport_rejects_arbitrary_command(self):
        with self.assertRaises(MODULE.InstallerError):
            MODULE.execute_apply({"command": ["sh", "-c", "anything"]}, b"")


if __name__ == "__main__":
    unittest.main()
