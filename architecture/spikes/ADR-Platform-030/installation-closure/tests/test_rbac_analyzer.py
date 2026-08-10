import importlib.util
import json
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("rbac_analyzer_test", HERE / "rbac_analyzer.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class RBACAnalyzerTests(unittest.TestCase):
    def test_m0a_report_reproduces_from_exact_manifest(self):
        protocol_path = HERE.parent / "m0a-installation" / "m0a-installation-v1.yaml"
        protocol = MODULE.V1.read_yaml_or_json(protocol_path)
        reviewed = MODULE.INSTALLER.verify_reviewed_object_set(protocol, protocol_path)
        actual = MODULE.analyze(reviewed, protocol_path)
        expected = json.loads((HERE / "evidence" / "m0ai-rbac-analysis.json").read_text())
        self.assertEqual(actual, expected)

    def test_m0a_sensitive_capabilities_are_not_suppressed(self):
        report = json.loads((HERE / "evidence" / "m0ai-rbac-analysis.json").read_text())
        findings = report["spec"]["summary"]["byFinding"]
        self.assertEqual(findings["SECRET-READ"], 2)
        self.assertEqual(findings["TOKENREVIEW"], 2)
        self.assertEqual(findings["SUBJECTACCESSREVIEW"], 2)
        self.assertEqual(findings["WILDCARD-RESOURCE-SCOPE"], 1)
        self.assertEqual(report["spec"]["decision"], "ANALYZED-NOT-ACCEPTED")

    def test_m0b_report_is_namespace_scoped_but_secret_sensitive(self):
        report = json.loads((HERE / "evidence" / "m0bi-rbac-analysis.json").read_text())
        self.assertEqual(report["spec"]["summary"]["roles"], 7)
        self.assertEqual(report["spec"]["summary"]["bindings"], 7)
        self.assertEqual(report["spec"]["summary"]["byFinding"]["SECRET-READ"], 7)
        self.assertEqual(report["spec"]["summary"]["byFinding"]["SECRET-WRITE"], 2)
        self.assertFalse(any(role["kind"] == "ClusterRole" for role in report["spec"]["roles"]))
        self.assertEqual(report["spec"]["decision"], "ANALYZED-NOT-ACCEPTED")

    def test_analyzer_detects_escalation_and_interactive_rules(self):
        role = {"kind": "ClusterRole", "namespace": None, "name": "test"}
        rule = {
            "apiGroups": [""],
            "resources": ["pods/exec"],
            "resourceNames": [],
            "nonResourceURLs": [],
            "verbs": ["create", "impersonate"],
        }
        findings = {item["finding"] for item in MODULE._findings(role, rule)}
        self.assertEqual(findings, {"POD-INTERACTIVE-SUBRESOURCE", "RBAC-ESCALATION-VERB"})


if __name__ == "__main__":
    unittest.main()
