import copy
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml


HARNESS_DIR = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ok141_phase_r_v5_test", HARNESS_DIR / "ok141_phase_r_v5.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PhaseRV5Tests(unittest.TestCase):
    def setUp(self):
        self.schema = HARNESS_DIR / "schema/contract-v3.schema.json"
        self.contract = HARNESS_DIR / "fixtures/contracts-v5/base.yaml"
        self.fixture = json.loads(
            (HARNESS_DIR / "fixtures/execution/phase-r-v5.json").read_text()
        )

    def test_v5_reproduces_and_v4_remains_historical(self):
        self.assertEqual(
            MODULE.validate(self.fixture, HARNESS_DIR), self.fixture["fixtureDigest"]
        )
        v4 = json.loads(
            (HARNESS_DIR / "fixtures/execution/phase-r-v4.json").read_text()
        )
        self.assertEqual(MODULE.V4.validate(v4, HARNESS_DIR), v4["fixtureDigest"])
        self.assertEqual(self.fixture["supersedes"]["fixtureDigest"], v4["fixtureDigest"])

    def test_provider_access_is_semantic_and_fail_closed(self):
        base = MODULE.V1.read_yaml_or_json(self.contract)
        _, base_r = MODULE.load_contract(self.contract, self.schema)
        mutations = {
            "secret-name": lambda d: d["spec"]["infrastructure"]["providerAccess"]["secretRef"].update(name="wrong"),
            "secret-namespace": lambda d: d["spec"]["infrastructure"]["providerAccess"]["secretRef"].update(namespace="wrong"),
            "provider-plane": lambda d: d["spec"]["infrastructure"]["providerAccess"].update(providerPlane="wrong"),
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, mutation in mutations.items():
                with self.subTest(name=name):
                    changed = copy.deepcopy(base)
                    mutation(changed)
                    path = root / f"{name}.yaml"
                    path.write_text(yaml.safe_dump(changed, sort_keys=False))
                    if name == "provider-plane":
                        with self.assertRaises(MODULE.V1.HarnessError):
                            MODULE.load_contract(path, self.schema)
                    else:
                        with self.assertRaises(MODULE.V1.HarnessError):
                            MODULE.load_contract(path, self.schema)
                    self.assertEqual(
                        MODULE.load_contract(self.contract, self.schema)[1], base_r
                    )

    def test_projection_binds_external_provider_without_credentials(self):
        projection = self.fixture["projection"]
        management = MODULE._documents(
            HARNESS_DIR / projection["managementObjectsPath"]
        )
        infrastructure = MODULE._documents(
            HARNESS_DIR / projection["infrastructurePrerequisitesPath"]
        )
        kubevirt_cluster = next(
            item for item in management if item["kind"] == "KubevirtCluster"
        )
        self.assertEqual(
            kubevirt_cluster["spec"]["infraClusterSecretRef"],
            self.fixture["clusterSemantics"]["infrastructure"]["providerAccess"]["secretRef"],
        )
        self.assertFalse(any(item.get("kind") == "Secret" for item in management + infrastructure))
        for requested in (
            projection["manifestPath"],
            projection["authorityMapPath"],
            projection["managementObjectsPath"],
            projection["infrastructurePrerequisitesPath"],
        ):
            content = (HARNESS_DIR / requested).read_text().lower()
            self.assertNotIn("client-key-data", content)
            self.assertNotIn("kubeconfig:", content)
            self.assertNotIn("stringdata:", content)

    def _copied_harness(self, temporary):
        copied = Path(temporary) / "harness"
        shutil.copytree(HARNESS_DIR, copied)
        fixture = json.loads(
            (copied / "fixtures/execution/phase-r-v5.json").read_text()
        )
        return copied, fixture

    def test_missing_provider_reference_and_secret_projection_fail_closed(self):
        for name in ("missing-reference", "projected-secret"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                copied, fixture = self._copied_harness(temporary)
                path = copied / fixture["projection"]["managementObjectsPath"]
                documents = MODULE._documents(path)
                if name == "missing-reference":
                    cluster = next(item for item in documents if item["kind"] == "KubevirtCluster")
                    cluster["spec"].pop("infraClusterSecretRef")
                else:
                    documents.append({
                        "apiVersion": "v1",
                        "kind": "Secret",
                        "metadata": {
                            "name": "forbidden",
                            "namespace": "disposable-ok141",
                            "annotations": {"openkubes.io/intent-revision": fixture["contract"]["R"]},
                        },
                    })
                path.write_text(yaml.safe_dump_all(documents, sort_keys=False, explicit_start=True))
                with self.assertRaises(MODULE.V1.HarnessError):
                    MODULE.validate(fixture, copied)

    def test_source_identity_tampering_fails_closed(self):
        mutations = {
            "source-commit": lambda d: d["source"].update(okClusterCommit="0" * 40),
            "renderer-digest": lambda d: d["source"]["files"]["renderer"].update(digest="sha256:" + "1" * 64),
            "ok-linux-commit": lambda d: d["source"].update(okLinuxCommit="2" * 40),
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                copied, fixture = self._copied_harness(temporary)
                manifest_path = copied / fixture["projection"]["manifestPath"]
                manifest = json.loads(manifest_path.read_text())
                mutation(manifest)
                manifest_path.write_text(MODULE.V1.jcs(manifest) + "\n")
                fixture["projection"]["manifestDigest"] = MODULE.V1.sha256_bytes(
                    manifest_path.read_bytes()
                )
                with self.assertRaises(MODULE.V1.HarnessError):
                    MODULE.validate(fixture, copied)

    def test_fixture_tampering_fails_closed(self):
        mutations = {
            "wrong-r": lambda d: d["contract"].update(R="sha256:" + "2" * 64),
            "wrong-tool": lambda d: d["tools"].update(phaseRV5ToolDigest="sha256:" + "3" * 64),
            "old-fixture": lambda d: d["supersedes"].update(fixtureDigest="sha256:" + "4" * 64),
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name):
                changed = copy.deepcopy(self.fixture)
                mutation(changed)
                with self.assertRaises(MODULE.V1.HarnessError):
                    MODULE.validate(changed, HARNESS_DIR)


if __name__ == "__main__":
    unittest.main()
