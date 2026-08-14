import copy
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "observe_recovery_snapshot_v2", ROOT / "observe_recovery_snapshot_v2.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CANDIDATE = ROOT / "recovery-snapshot-candidate-v2.yaml"


class RecoverySnapshotV2Tests(unittest.TestCase):
    def test_v2_is_reproducible_and_v1_is_historical(self):
        candidate = MODULE.verify_candidate(CANDIDATE)
        self.assertEqual(candidate["spec"]["supersedes"]["candidateDigest"], "sha256:1748e1ae7bec8726fd5de8ca30699fa3f9b8c4650e946ef9373d6a63e926ba48")
        self.assertFalse(candidate["spec"]["authorization"]["readOnlyGranted"])

    def test_only_two_mgmt_kubevirt_collections_allow_api_absence(self):
        candidate = MODULE.V1.read(CANDIDATE)
        allowed = {
            query["id"]
            for query in candidate["spec"]["planes"]["ok-mgmt"]["queries"]
            if query.get("allowAPIResourceAbsent")
        }
        self.assertEqual(allowed, MODULE.API_ABSENCE_IDS)
        changed = copy.deepcopy(candidate)
        changed["spec"]["planes"]["ok-infra"]["queries"][-1]["allowAPIResourceAbsent"] = True
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "candidate.yaml"
            path.write_text(yaml.safe_dump(changed, sort_keys=False))
            with self.assertRaises(MODULE.SnapshotError):
                MODULE.verify_candidate(path)

    def test_bound_api_not_served_is_retained_without_raw_error(self):
        query = {
            "id": "local-provider-vms",
            "mode": "collection",
            "rawURI": "/apis/kubevirt.io/v1/namespaces/disposable-ok141/virtualmachines",
            "labelSelector": "cluster.x-k8s.io/cluster-name=disposable-ok141",
            "allowAPIResourceAbsent": True,
        }

        def runner(*args, **kwargs):
            return subprocess.CompletedProcess(
                args[0], 1, "", "Error from server (NotFound): the server could not find the requested resource"
            )

        result = MODULE.run_query(Path("/tmp/kubectl"), Path("/tmp/kubeconfig"), query, runner)
        self.assertEqual(result, {"id": "local-provider-vms", "outcome": "API_NOT_SERVED", "objects": []})

    def test_other_collection_failure_still_fails_closed(self):
        query = {
            "id": "machines",
            "mode": "collection",
            "rawURI": "/apis/cluster.x-k8s.io/v1beta2/namespaces/disposable-ok141/machines",
            "labelSelector": "cluster.x-k8s.io/cluster-name=disposable-ok141",
        }

        def runner(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 1, "", "connection refused")

        with self.assertRaises(MODULE.SnapshotError):
            MODULE.run_query(Path("/tmp/kubectl"), Path("/tmp/kubeconfig"), query, runner)

    def test_success_response_still_retains_metadata_only(self):
        query = {"id": "one", "mode": "exact", "rawURI": "/api/v1/namespaces/x"}
        response = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": "x", "uid": "uid", "resourceVersion": "9"},
            "data": {"forbidden": "payload"},
        }

        def runner(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 0, json.dumps(response), "")

        result = MODULE.run_query(Path("/tmp/kubectl"), Path("/tmp/kubeconfig"), query, runner)
        self.assertEqual(result["objects"][0]["uid"], "uid")
        self.assertNotIn("data", result["objects"][0])


if __name__ == "__main__":
    unittest.main()
