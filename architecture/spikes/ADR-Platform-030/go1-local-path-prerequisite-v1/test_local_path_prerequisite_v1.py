import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_local_path_prerequisite_test", HERE / "bounded_local_path_prerequisite_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class LocalPathPrerequisiteTests(unittest.TestCase):
    def test_candidate_is_inert_and_exact(self):
        candidate = MODULE.validate_candidate()
        self.assertEqual(candidate["spec"]["authorization"]["decision"], "NO-GO")
        self.assertTrue(all(not value for key, value in candidate["spec"]["authorization"].items() if key.endswith("Granted")))
        self.assertEqual(len(candidate["spec"]["objects"]), 9)

    def test_projection_is_source_locked_and_reproducible(self):
        values = MODULE.RENDERER.render()
        self.assertEqual(MODULE.RENDERER.sha(MODULE.RENDERER.SOURCE), MODULE.RENDERER.SOURCE_DIGEST)
        self.assertEqual(MODULE.RENDERER.canonical_digest(values), "sha256:e8b8996c1ae052d0dcfac83906cebfbe95293f15a3ae2825523f6ee0dabda240")

    def test_images_and_required_metadata_are_pinned(self):
        candidate = MODULE.validate_candidate()
        values = MODULE.projected_objects(candidate)
        self.assertIn("@sha256:", values["deployment"]["spec"]["template"]["spec"]["containers"][0]["image"])
        helper = yaml.safe_load(values["configmap"]["data"]["helperPod.yaml"])
        self.assertIn("@sha256:", helper["spec"]["containers"][0]["image"])
        self.assertEqual(values["storageclass"]["metadata"]["annotations"]["storageclass.kubernetes.io/is-default-class"], "true")
        self.assertEqual(values["namespace"]["metadata"]["labels"], MODULE.RENDERER.PSA)

    def test_readiness_requires_all_three_claims(self):
        candidate = MODULE.validate_candidate()
        generation = {"metadata": {"generation": 1}, "status": {"availableReplicas": 1, "observedGeneration": 1}}
        storage = {"provisioner": "rancher.io/local-path", "volumeBindingMode": "WaitForFirstConsumer", "reclaimPolicy": "Delete", "metadata": {"annotations": {"storageclass.kubernetes.io/is-default-class": "true"}}}
        namespace = {"metadata": {"labels": MODULE.RENDERER.PSA}}
        def runner(command, **_kwargs):
            uri = command[-1]
            value = generation if "deployments" in uri else storage if "storageclasses" in uri else namespace
            return subprocess.CompletedProcess(command, 0, json.dumps(value).encode(), b"")
        result = MODULE.readiness(Path("kubectl"), Path("kubeconfig"), candidate, runner, lambda _seconds: None)
        self.assertEqual(result["attempts"], 1)
        self.assertTrue(all(value is True for key, value in result.items() if key != "attempts"))

    def test_exact_create_rejects_missing_server_identity(self):
        def runner(command, **_kwargs):
            return subprocess.CompletedProcess(command, 0, b'{"metadata":{}}', b"")
        with self.assertRaises(MODULE.PrerequisiteError):
            MODULE.create_exact(Path("kubectl"), Path("kubeconfig"), "/api/v1/namespaces", {"kind": "Namespace"}, runner)


if __name__ == "__main__":
    unittest.main()
