import importlib.util
import sys
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_platform_rbac_test", HERE / "bounded_platform_rbac_remediation_v1.py")
RBAC = importlib.util.module_from_spec(SPEC); sys.modules[SPEC.name] = RBAC
assert SPEC.loader is not None; SPEC.loader.exec_module(RBAC)


class RBACTests(unittest.TestCase):
    def test_candidate_and_template_are_inert(self):
        self.assertEqual(RBAC.validate_candidate()["spec"]["authorization"]["decision"], "NO-GO")
        self.assertEqual(yaml.safe_load((HERE / "platform-rbac-remediation-grant-v1.template.yaml").read_text())["spec"]["decision"], "NO-GO")

    def test_amendment_adds_only_exact_rule_and_preserves_input(self):
        value = {"metadata": {"uid": "u", "resourceVersion": "1", "managedFields": [{}]}, "rules": [{"apiGroups": [""], "resources": ["pods"], "verbs": ["get"]}]}
        item = {"id": "x", "apiGroup": "", "resources": ["resourcequotas"], "verbs": ["list"]}
        result = RBAC.amended(value, item)
        self.assertEqual(result["rules"][-1], {"apiGroups": [""], "resources": ["resourcequotas"], "verbs": ["list"]})
        self.assertEqual(len(value["rules"]), 1)
        self.assertNotIn("managedFields", result["metadata"])

    def test_existing_superset_fails_closed(self):
        value = {"metadata": {}, "rules": [{"apiGroups": ["cilium.io"], "resources": ["ciliumpodippools"], "verbs": ["get", "list", "watch"]}]}
        item = {"id": "x", "apiGroup": "cilium.io", "resources": ["ciliumpodippools"], "verbs": ["list"]}
        with self.assertRaises(RBAC.RBACError): RBAC.amended(value, item)

    def test_authority_declares_non_atomic_side_effect(self):
        self.assertIn("nonAtomicPartialStateAccepted", RBAC.TRUE)
        self.assertIn("automaticArgoReconciliationAcknowledged", RBAC.TRUE)
        self.assertIn("retryGranted", RBAC.FALSE)


if __name__ == "__main__": unittest.main()
