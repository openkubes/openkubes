import importlib.util
import sys
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_platform_auth_cause_test", HERE / "bounded_platform_authorization_cause_v1.py")
CAUSE = importlib.util.module_from_spec(SPEC); sys.modules[SPEC.name] = CAUSE
assert SPEC.loader is not None; SPEC.loader.exec_module(CAUSE)


class CauseTests(unittest.TestCase):
    def test_candidate_and_template_are_inert(self):
        self.assertEqual(CAUSE.validate_candidate()["spec"]["authorization"]["decision"], "NO-GO")
        template = yaml.safe_load((HERE / "platform-authorization-cause-grant-v1.template.yaml").read_text())
        self.assertEqual(template["spec"]["decision"], "NO-GO")

    def test_extracts_namespaced_resource_without_subject(self):
        message = 'User "secret-subject" cannot list resource "pods" in API group "" in the namespace "ok-observability"'
        self.assertEqual(CAUSE.extract_findings(message), [{"kind": "RESOURCE", "verb": "list", "apiGroup": "", "resource": "pods", "scope": "NAMESPACE", "namespaceCategory": "OK-OBSERVABILITY"}])
        self.assertNotIn("secret-subject", str(CAUSE.extract_findings(message)))

    def test_extracts_cluster_resource_and_redacts_other_namespace(self):
        cluster = 'cannot get resource "customresourcedefinitions" in API group "apiextensions.k8s.io" at the cluster scope'
        other = 'cannot watch resource "secrets" in API group "" in the namespace "private-name"'
        self.assertEqual(CAUSE.extract_findings(cluster)[0]["scope"], "CLUSTER")
        self.assertEqual(CAUSE.extract_findings(other)[0]["namespaceCategory"], "OTHER")
        self.assertNotIn("private-name", str(CAUSE.extract_findings(other)))

    def test_extracts_only_categorized_nonresource_path(self):
        self.assertEqual(CAUSE.extract_findings('cannot get path "/version"')[0]["pathCategory"], "VERSION")
        finding = CAUSE.extract_findings('cannot get non-resource URL "/private/path"')[0]
        self.assertEqual(finding["pathCategory"], "OTHER")
        self.assertNotIn("private", str(finding))

    def test_authority_is_read_only(self):
        self.assertFalse(set(CAUSE.TRUE) & set(CAUSE.FALSE))
        self.assertIn("mutationGranted", CAUSE.FALSE)


if __name__ == "__main__": unittest.main()
