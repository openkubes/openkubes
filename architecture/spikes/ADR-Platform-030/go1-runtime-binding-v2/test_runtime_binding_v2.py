import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("binding", HERE / "bounded_runtime_binding_v2.py")
binding = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(binding)


class RuntimeBindingTests(unittest.TestCase):
    def test_candidate_is_fail_closed(self):
        value = binding.validate_candidate()
        self.assertEqual(value["spec"]["authorization"]["decision"], "NO-GO")
        self.assertEqual(value["spec"]["workload"]["queries"], {
            "kubeSystem": "/api/v1/namespaces/kube-system",
            "localPath": "/apis/storage.k8s.io/v1/storageclasses/local-path",
        })

    def test_kubeconfig_extracts_https_ca(self):
        raw = b"""apiVersion: v1
current-context: c
contexts: [{name: c, context: {cluster: x, user: u}}]
clusters: [{name: x, cluster: {server: 'https://example.invalid:6443', certificate-authority-data: 'Y2E='}}]
users: [{name: u, user: {token: redacted}}]
"""
        server, encoded, fingerprint = binding.kubeconfig_values(raw)
        self.assertEqual(server, "https://example.invalid:6443")
        self.assertEqual(encoded, "Y2E=")
        self.assertEqual(fingerprint, binding.sha_bytes(b"ca"))

    def test_kubeconfig_rejects_non_https(self):
        raw = b"""apiVersion: v1
current-context: c
contexts: [{name: c, context: {cluster: x, user: u}}]
clusters: [{name: x, cluster: {server: 'http://example.invalid', certificate-authority-data: 'Y2E='}}]
"""
        with self.assertRaises(binding.BindingError):
            binding.kubeconfig_values(raw)


if __name__ == "__main__":
    unittest.main()
