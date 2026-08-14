import base64
import copy
import importlib.util
import json
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("lb_remediation", HERE / "bounded_lb_namespace_remediation_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RemediationTests(unittest.TestCase):
    def setUp(self):
        self.candidate = yaml.safe_load((HERE / "lb-namespace-remediation-candidate-v1.yaml").read_text())
        self.spec = self.candidate["spec"]
        self.kubeconfig = {
            "apiVersion": "v1",
            "kind": "Config",
            "current-context": "provider",
            "clusters": [{"name": "infra", "cluster": {"server": "https://infra", "certificate-authority-data": "SECRET-CA"}}],
            "users": [{"name": "admin", "user": {"client-key-data": "SECRET-KEY"}}],
            "contexts": [{"name": "provider", "context": {"cluster": "infra", "user": "admin", "namespace": "ok-obs-verify"}}],
        }

    def test_candidate_is_no_go_and_bounded(self):
        plan = MODULE.plan()
        self.assertEqual(plan["authorization"], "NO-GO")
        self.assertFalse(plan["clusterContacted"])
        self.assertFalse(plan["mutationPerformed"])
        self.assertEqual(self.spec["exclusions"]["generalCleanupGranted"], False)

    def test_normalization_changes_only_current_context_namespace(self):
        raw = yaml.safe_dump(self.kubeconfig, sort_keys=False).encode()
        result = yaml.safe_load(MODULE.normalize_kubeconfig(raw, "ok-obs-verify", "disposable-ok141"))
        expected = copy.deepcopy(self.kubeconfig)
        expected["contexts"][0]["context"]["namespace"] = "disposable-ok141"
        self.assertEqual(result, expected)

    def test_normalization_rejects_unexpected_old_namespace(self):
        changed = copy.deepcopy(self.kubeconfig)
        changed["contexts"][0]["context"]["namespace"] = "other"
        with self.assertRaises(MODULE.RemediationError):
            MODULE.normalize_kubeconfig(yaml.safe_dump(changed).encode(), "ok-obs-verify", "disposable-ok141")

    def test_secret_replacement_is_redacted_and_preserves_identity(self):
        secret = {
            "apiVersion": "v1", "kind": "Secret", "type": "Opaque",
            "metadata": {"name": "external-infra-kubeconfig-disposable-ok141", "namespace": "disposable-ok141", "uid": "uid-1", "resourceVersion": "7"},
            "data": {"kubeconfig": base64.b64encode(yaml.safe_dump(self.kubeconfig).encode()).decode()},
        }
        payload, evidence = MODULE.build_secret_replacement(secret, self.spec)
        updated = json.loads(payload)
        normalized = yaml.safe_load(base64.b64decode(updated["data"]["kubeconfig"]))
        self.assertEqual(normalized["contexts"][0]["context"]["namespace"], "disposable-ok141")
        self.assertNotIn("SECRET-KEY", json.dumps(evidence))
        self.assertFalse(evidence["secretBytesEmitted"])
        self.assertEqual(updated["metadata"]["resourceVersion"], "7")

    def test_target_service_pins_existing_vip_and_exact_selector(self):
        service = json.loads(MODULE.build_target_service(self.spec))
        self.assertEqual(service["metadata"]["namespace"], "disposable-ok141")
        self.assertEqual(service["metadata"]["annotations"]["metallb.io/loadBalancerIPs"], "192.168.100.213")
        self.assertEqual(service["metadata"]["annotations"]["metallb.io/address-pool"], "ok-pool")
        self.assertEqual(service["spec"]["selector"], self.spec["objects"]["targetService"]["selector"])

    def test_kubevirt_patch_has_concurrency_and_value_tests(self):
        value = {
            "apiVersion": "infrastructure.cluster.x-k8s.io/v1alpha1", "kind": "KubevirtCluster",
            "metadata": {"name": "disposable-ok141", "namespace": "disposable-ok141", "uid": "uid-kvc", "resourceVersion": "12"},
            "spec": {"controlPlaneEndpoint": {"host": "192.168.100.213", "port": 6443}},
        }
        patch = json.loads(MODULE.kubevirt_cluster_patch(value, self.spec))
        self.assertEqual(patch[:3], [
            {"op": "test", "path": "/metadata/uid", "value": "uid-kvc"},
            {"op": "test", "path": "/metadata/resourceVersion", "value": "12"},
            {"op": "test", "path": "/spec/controlPlaneEndpoint/host", "value": "192.168.100.213"},
        ])
        self.assertEqual(patch[3], {"op": "replace", "path": "/spec/controlPlaneEndpoint/host", "value": ""})

    def test_old_service_validation_requires_bound_vip_and_pool(self):
        service = {
            "apiVersion": "v1", "kind": "Service",
            "metadata": {"name": "disposable-ok141-lb", "namespace": "ok-obs-verify", "uid": "uid", "resourceVersion": "1", "annotations": {"metallb.io/ip-allocated-from-pool": "ok-pool"}},
            "spec": {"selector": self.spec["objects"]["targetService"]["selector"]},
            "status": {"loadBalancer": {"ingress": [{"ip": "192.168.100.213"}]}},
        }
        self.assertEqual(MODULE.validate_misplaced_service(service, self.spec), {"uid": "uid", "resourceVersion": "1"})
        service["status"]["loadBalancer"]["ingress"][0]["ip"] = "192.168.100.214"
        with self.assertRaises(MODULE.RemediationError):
            MODULE.validate_misplaced_service(service, self.spec)


if __name__ == "__main__":
    unittest.main()
