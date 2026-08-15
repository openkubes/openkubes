import importlib.util
import json
from pathlib import Path
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("live_amendment", HERE / "bounded_live_platform_network_amendment_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LiveAmendmentTests(unittest.TestCase):
    def test_replace_preserves_uid_and_resource_version(self):
        current = {"metadata": {"uid": "u", "resourceVersion": "7", "annotations": {}}}
        value = json.loads(MODULE.amended_document(current, {"openkubes.io/intent-revision": "r"}))
        self.assertEqual(value["metadata"]["uid"], "u")
        self.assertEqual(value["metadata"]["resourceVersion"], "7")
        self.assertEqual(value["metadata"]["annotations"]["openkubes.io/intent-revision"], "r")

    def test_uri_is_exact(self):
        self.assertEqual(MODULE.uri("", "v1", "argocd", "secrets", "x"), "/api/v1/namespaces/argocd/secrets/x")
        self.assertEqual(MODULE.uri("cluster.x-k8s.io", "v1beta1", "n", "clusters", "x"), "/apis/cluster.x-k8s.io/v1beta1/namespaces/n/clusters/x")


if __name__ == "__main__":
    unittest.main()
