import base64
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_registration_remediation_test", HERE / "bounded_registration_audience_remediation_v1.py")
REMEDIATION = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = REMEDIATION
assert SPEC.loader is not None
SPEC.loader.exec_module(REMEDIATION)


class RegistrationAudienceRemediationTests(unittest.TestCase):
    def test_candidate_and_template_are_inert(self):
        candidate = REMEDIATION.validate_candidate()
        self.assertEqual(candidate["spec"]["authorization"]["decision"], "NO-GO")
        grant = yaml.safe_load((HERE / "registration-audience-remediation-grant-v1.template.yaml").read_text())
        self.assertEqual(grant["spec"]["decision"], "NO-GO")

    def test_replacement_changes_only_bound_credential_fields(self):
        old_config = {"bearerToken": "old", "tlsClientConfig": {"insecure": False, "caData": "ca"}}
        current = {
            "apiVersion": "v1", "kind": "Secret", "type": "Opaque",
            "metadata": {"name": "disposable-ok141-cluster", "namespace": "argocd", "uid": "u", "resourceVersion": "10", "labels": {"l": "v"}, "annotations": {"a": "b"}, "managedFields": [{}]},
            "data": {"config": base64.b64encode(json.dumps(old_config).encode()).decode(), "name": base64.b64encode(b"disposable-ok141").decode()},
        }
        result = REMEDIATION.replacement_secret(current, "new", "expiry")
        config = json.loads(base64.b64decode(result["data"]["config"]))
        self.assertEqual(config["bearerToken"], "new")
        self.assertEqual(config["tlsClientConfig"], old_config["tlsClientConfig"])
        self.assertEqual(result["metadata"]["uid"], "u")
        self.assertEqual(result["metadata"]["resourceVersion"], "10")
        self.assertEqual(result["metadata"]["annotations"], {"a": "b", "openkubes.io/token-expiration": "expiry"})
        self.assertNotIn("managedFields", result["metadata"])
        self.assertEqual(current["data"]["config"], base64.b64encode(json.dumps(old_config).encode()).decode())

    def test_raw_replace_is_exact_put(self):
        calls = []
        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, b"{}", b"")
        code, _, _ = REMEDIATION.raw_replace(Path("/tmp/kubectl"), Path("/tmp/shared"), "/secret", {"kind": "Secret"}, runner)
        self.assertEqual(code, 0)
        self.assertEqual(calls[0][0], ["/tmp/kubectl", "--kubeconfig", "/tmp/shared", "replace", "--raw", "/secret", "--filename", "-"])

    def test_authority_sets_are_disjoint_and_side_effect_is_explicit(self):
        self.assertFalse(set(REMEDIATION.TRUE) & set(REMEDIATION.FALSE))
        self.assertIn("automaticArgoReconciliationAcknowledged", REMEDIATION.TRUE)
        self.assertIn("platformObserverOrCapabilityTestGranted", REMEDIATION.FALSE)


if __name__ == "__main__":
    unittest.main()
