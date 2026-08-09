import argparse
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import yaml


HARNESS_DIR = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ok141_harness", HARNESS_DIR / "ok141_harness.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.schema = HARNESS_DIR / "schema/contract-v1.schema.json"
        self.contracts = HARNESS_DIR / "fixtures/contracts"
        self.base_evidence = json.loads(
            (HARNESS_DIR / "fixtures/evaluator/base.json").read_text()
        )
        self.enablement_dir = HARNESS_DIR / "profiles/enablement/cilium-fixture-v1"
        self.platform_dir = HARNESS_DIR / "profiles/platform/minimal-observability-v1"
        self.execution_fixture = json.loads(
            (HARNESS_DIR / "fixtures/execution/phase-r-v1.json").read_text()
        )

    def canonicalize(self, input_path, directory):
        normalized = directory / "contract.json"
        manifest = directory / "canonicalization.json"
        MODULE.canonicalize(argparse.Namespace(
            profile=MODULE.PROFILE,
            schema=self.schema,
            input=input_path,
            normalized_output=normalized,
            manifest_output=manifest,
        ))
        return json.loads(normalized.read_text()), json.loads(manifest.read_text())

    def test_equivalent_contracts_have_same_semantic_revision(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            normalized_a, manifest_a = self.canonicalize(self.contracts / "base.yaml", root / "a")
            normalized_b, manifest_b = self.canonicalize(self.contracts / "equivalent.yaml", root / "b")
            self.assertEqual(normalized_a, normalized_b)
            self.assertEqual(manifest_a["normalizedContractDigest"], manifest_b["normalizedContractDigest"])
            self.assertNotEqual(manifest_a["rawArtifactDigest"], manifest_b["rawArtifactDigest"])

    def test_semantic_change_changes_revision(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, original = self.canonicalize(self.contracts / "base.yaml", root / "a")
            changed = (self.contracts / "base.yaml").read_text().replace("v1.36.2", "v1.36.3")
            changed_path = root / "changed.yaml"
            changed_path.write_text(changed)
            _, modified = self.canonicalize(changed_path, root / "b")
            self.assertNotEqual(original["normalizedContractDigest"], modified["normalizedContractDigest"])

    def test_duplicate_and_unknown_fields_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for fixture in ("duplicate.yaml", "unknown.yaml"):
                with self.subTest(fixture=fixture), self.assertRaises(MODULE.HarnessError):
                    self.canonicalize(self.contracts / fixture, root / fixture)

    def evaluate(self, mutate=None):
        document = copy.deepcopy(self.base_evidence)
        if mutate:
            mutate(document)
        return MODULE.evaluate_document(document)

    def test_evaluator_positive_and_negative_controls(self):
        cases = {
            "valid-current": (None, "True"),
            "stale-generation": (lambda d: d["sources"][0].update(observedGeneration=1), "Unknown"),
            "wrong-r": (lambda d: d["sources"][0].update(intentRevision="sha256:" + "9" * 64), "Unknown"),
            "wrong-e": (lambda d: d["sources"][2].update(observedRevision="sha256:" + "8" * 64), "Unknown"),
            "wrong-p": (lambda d: d["sources"][3].update(observedRevision="sha256:" + "7" * 64), "Unknown"),
            "missing-observer": (lambda d: d["sources"][2].update(observerAvailable=False), "Unknown"),
            "conflicting-authority": (lambda d: d["sources"][0].update(conflictingAuthority=True), "Unknown"),
            "current-failure": (lambda d: d["sources"][3].update(status="False", reason="ApplicationOutOfSync", historicalStatus="True"), "False"),
            "missing-source": (lambda d: d.update(sources=d["sources"][:-1]), "Unknown"),
        }
        for name, (mutation, expected) in cases.items():
            with self.subTest(name=name):
                self.assertEqual(self.evaluate(mutation)["ready"]["status"], expected)

    def test_current_false_precedes_unrelated_unknown(self):
        def mutation(document):
            document["sources"][0]["observerAvailable"] = False
            document["sources"][3]["status"] = "False"
        self.assertEqual(self.evaluate(mutation)["ready"]["status"], "False")

    def test_missing_revision_fields_fail_instead_of_comparing_none(self):
        def mutation(document):
            del document["sources"][0]["expectedRevision"]
            del document["sources"][0]["observedRevision"]
        with self.assertRaises(MODULE.HarnessError):
            self.evaluate(mutation)

    def test_bundle_detects_tampered_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            artifact = root / "result.json"
            MODULE.write_canonical(artifact, self.evaluate())
            manifest = root / "manifest.json"
            MODULE.bundle(argparse.Namespace(root=root, output=manifest, artifact=["result.json"]))
            MODULE.verify(argparse.Namespace(root=root, manifest=manifest))
            artifact.write_text("tampered\n")
            with self.assertRaises(MODULE.HarnessError):
                MODULE.verify(argparse.Namespace(root=root, manifest=manifest))

    def test_enablement_revision_changes_with_values_or_artifact(self):
        profile = json.loads((self.enablement_dir / "profile.json").read_text())
        values = MODULE.read_yaml_or_json(self.enablement_dir / "values.yaml")
        original = MODULE.validate_enablement_profile(profile, values)
        changed_values = copy.deepcopy(values)
        changed_values["operator"]["replicas"] = 2
        with self.assertRaises(MODULE.HarnessError):
            MODULE.validate_enablement_profile(profile, changed_values)
        changed_profile = copy.deepcopy(profile)
        changed_profile["package"]["artifactDigest"] = "sha256:" + "3" * 64
        changed_profile["package"]["valuesDigest"] = MODULE.semantic_revision(values)
        self.assertNotEqual(original, MODULE.validate_enablement_profile(changed_profile, values))
        mutable_image = copy.deepcopy(profile)
        mutable_image["renderedImages"][0] = "quay.io/cilium/cilium:v1.19.6"
        with self.assertRaises(MODULE.HarnessError):
            MODULE.validate_enablement_profile(mutable_image, values)
        missing_sources = copy.deepcopy(profile)
        missing_sources["requiredSources"] = []
        with self.assertRaises(MODULE.HarnessError):
            MODULE.validate_enablement_profile(missing_sources, values)

    def test_platform_membership_revision_and_target_fail_closed(self):
        profile = json.loads((self.platform_dir / "profile.json").read_text())
        applications = list(yaml.load_all(
            (self.platform_dir / "applications.yaml").read_text(),
            Loader=MODULE.UniqueKeyLoader,
        ))
        original = MODULE.validate_platform_applications(profile, applications)
        changed_leaf = copy.deepcopy(profile)
        changed_leaf["requiredApplications"][0]["source"]["commit"] = "1" * 40
        self.assertNotEqual(original, MODULE.semantic_revision(changed_leaf))
        missing = []
        with self.assertRaises(MODULE.HarnessError):
            MODULE.validate_platform_applications(profile, missing)
        mutable = copy.deepcopy(applications)
        mutable[0]["spec"]["source"]["targetRevision"] = "main"
        with self.assertRaises(MODULE.HarnessError):
            MODULE.validate_platform_applications(profile, mutable)
        wrong_target = copy.deepcopy(applications)
        wrong_target[0]["spec"]["destination"]["name"] = "foreign-cluster"
        with self.assertRaises(MODULE.HarnessError):
            MODULE.validate_platform_applications(profile, wrong_target)
        no_checks = copy.deepcopy(profile)
        no_checks["requiredApplications"][0]["capabilityChecks"] = []
        with self.assertRaises(MODULE.HarnessError):
            MODULE.validate_platform_applications(no_checks, applications)
        extra = copy.deepcopy(applications)
        duplicate = copy.deepcopy(applications[0])
        duplicate["metadata"]["name"] = "unexpected-extra"
        extra.append(duplicate)
        with self.assertRaises(MODULE.HarnessError):
            MODULE.validate_platform_applications(profile, extra)

    def test_execution_fixture_reproduces_distinct_fixture_digest(self):
        digest = MODULE.validate_execution_fixture(self.execution_fixture, HARNESS_DIR)
        self.assertEqual(digest, self.execution_fixture["fixtureDigest"])
        self.assertNotEqual(digest, self.execution_fixture["contract"]["R"])
        self.assertEqual(
            {item["id"] for item in self.execution_fixture["negativeControls"]},
            MODULE.NEGATIVE_CONTROL_IDS,
        )

    def test_execution_fixture_fails_closed_on_identity_tampering(self):
        mutations = {
            "wrong-r": lambda d: d["contract"].update(R="sha256:" + "1" * 64),
            "wrong-e": lambda d: d["enablement"].update(E="sha256:" + "2" * 64),
            "wrong-p": lambda d: d["platform"].update(P="sha256:" + "3" * 64),
            "wrong-tool": lambda d: d["tools"].update(harnessDigest="sha256:" + "4" * 64),
            "missing-control": lambda d: d.update(negativeControls=d["negativeControls"][:-1]),
            "changed-connectivity": lambda d: d["connectivity"].update(podCIDR="10.50.0.0/16"),
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name):
                document = copy.deepcopy(self.execution_fixture)
                mutation(document)
                with self.assertRaises(MODULE.HarnessError):
                    MODULE.validate_execution_fixture(document, HARNESS_DIR)


if __name__ == "__main__":
    unittest.main()
