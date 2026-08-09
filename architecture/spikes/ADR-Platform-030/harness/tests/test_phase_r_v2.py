import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import yaml


HARNESS_DIR = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ok141_phase_r_v2", HARNESS_DIR / "ok141_phase_r_v2.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PhaseRV2Tests(unittest.TestCase):
    def setUp(self):
        self.schema = HARNESS_DIR / "schema/contract-v2.schema.json"
        self.contract = HARNESS_DIR / "fixtures/contracts-v2/base.yaml"
        self.fixture = json.loads(
            (HARNESS_DIR / "fixtures/execution/phase-r-v2.json").read_text()
        )

    def test_complete_cluster_semantics_reproduce_r(self):
        normalized, revision = MODULE.load_contract(self.contract, self.schema)
        self.assertEqual(revision, self.fixture["contract"]["R"])
        self.assertEqual(normalized["spec"]["topology"]["workers"]["replicas"], 1)
        self.assertEqual(
            normalized["spec"]["operatingSystem"]["identity"],
            "sha256:7f5dd4276432f522727a50e604538b6befc0cac51ee2b90d4b1ccbfcac774a2d",
        )

    def test_equivalent_contract_and_semantic_changes(self):
        base = MODULE.V1.read_yaml_or_json(self.contract)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            equivalent = copy.deepcopy(base)
            equivalent["metadata"]["uid"] = "non-semantic-runtime-uid"
            equivalent["metadata"]["generation"] = 9
            equivalent_path = root / "equivalent.yaml"
            equivalent_path.write_text(yaml.safe_dump(equivalent, sort_keys=True))
            _, base_r = MODULE.load_contract(self.contract, self.schema)
            _, equivalent_r = MODULE.load_contract(equivalent_path, self.schema)
            self.assertEqual(base_r, equivalent_r)

            for name, mutate in {
                "worker-count": lambda d: d["spec"]["topology"]["workers"].update(replicas=2),
                "worker-disk": lambda d: d["spec"]["topology"]["workers"]["machine"].update(disk="20Gi"),
                "os-identity": lambda d: d["spec"]["operatingSystem"].update(identity="sha256:" + "1" * 64),
                "provider-profile": lambda d: d["spec"]["infrastructure"]["profile"].update(identity="sha256:" + "2" * 64),
            }.items():
                with self.subTest(name=name):
                    changed = copy.deepcopy(base)
                    mutate(changed)
                    changed_path = root / f"{name}.yaml"
                    changed_path.write_text(yaml.safe_dump(changed, sort_keys=False))
                    _, changed_r = MODULE.load_contract(changed_path, self.schema)
                    self.assertNotEqual(base_r, changed_r)

    def test_v2_fixture_reproduces_and_v1_is_only_superseded(self):
        digest = MODULE.validate_execution_fixture_v2(self.fixture, HARNESS_DIR)
        self.assertEqual(digest, self.fixture["fixtureDigest"])
        self.assertEqual(
            self.fixture["supersedes"]["fixtureDigest"],
            "sha256:a97e1e31e1f09cc44210679b48130e36edd90709d84ba3ee7b729ba5df82c9ba",
        )
        v1 = json.loads(
            (HARNESS_DIR / "fixtures/execution/phase-r-v1.json").read_text()
        )
        self.assertEqual(
            MODULE.V1.validate_execution_fixture(v1, HARNESS_DIR),
            v1["fixtureDigest"],
        )

    def test_authority_sets_are_exact_and_fail_closed(self):
        projection = self.fixture["projection"]
        management = MODULE._read_documents(HARNESS_DIR / projection["managementObjectsPath"])
        infrastructure = MODULE._read_documents(
            HARNESS_DIR / projection["infrastructurePrerequisitesPath"]
        )
        self.assertEqual(len(management), 8)
        self.assertEqual(len(infrastructure), 3)
        self.assertFalse(
            any(
                item["apiVersion"].split("/", 1)[0] in MODULE.CAPI_GROUPS
                for item in infrastructure
            )
        )
        authority = json.loads(
            (HARNESS_DIR / projection["authorityMapPath"]).read_text()
        )
        self.assertEqual(authority["managementPlane"]["identity"], "ok-mgmt")
        self.assertEqual(authority["infrastructurePlane"]["identity"], "ok-infra")
        self.assertTrue(authority["excludedRendererArtifacts"])

        tampered = copy.deepcopy(self.fixture)
        tampered["projection"]["objectSets"]["okMgmtLifecycle"]["count"] = 9
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate_execution_fixture_v2(tampered, HARNESS_DIR)

    def test_fixture_identity_tampering_fails_closed(self):
        mutations = {
            "wrong-r": lambda d: d["contract"].update(R="sha256:" + "1" * 64),
            "wrong-e": lambda d: d["enablement"].update(E="sha256:" + "2" * 64),
            "wrong-p": lambda d: d["platform"].update(P="sha256:" + "3" * 64),
            "wrong-tool": lambda d: d["tools"].update(phaseRV2ToolDigest="sha256:" + "4" * 64),
            "old-fixture-mutated": lambda d: d["supersedes"].update(fixtureDigest="sha256:" + "5" * 64),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                tampered = copy.deepcopy(self.fixture)
                mutate(tampered)
                with self.assertRaises(MODULE.V1.HarnessError):
                    MODULE.validate_execution_fixture_v2(tampered, HARNESS_DIR)

    def test_fresh_projection_matches_pinned_sibling_sources_when_available(self):
        repository = HARNESS_DIR.parents[3]
        ok_cluster = repository.parent / "ok-cluster"
        ok_linux = repository.parent / "ok-linux"
        if not ok_cluster.is_dir() or not ok_linux.is_dir():
            self.skipTest("pinned sibling sources are not available in this checkout")
        digest = MODULE.validate_execution_fixture_v2(
            self.fixture, HARNESS_DIR, ok_cluster, ok_linux
        )
        self.assertEqual(digest, self.fixture["fixtureDigest"])


if __name__ == "__main__":
    unittest.main()
