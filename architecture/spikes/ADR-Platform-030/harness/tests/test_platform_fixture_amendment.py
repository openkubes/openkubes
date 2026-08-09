import copy
import importlib.util
import json
import subprocess
import unittest
from pathlib import Path

import yaml


HARNESS_DIR = Path(__file__).resolve().parents[1]


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HARNESS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PLATFORM = load_module("ok141_platform_amendment_test", "ok141_platform_amendment.py")
PHASE = load_module("ok141_phase_r_v3_test", "ok141_phase_r_v3.py")


class PlatformFixtureAmendmentTests(unittest.TestCase):
    def setUp(self):
        self.profile_path = HARNESS_DIR / "profiles/platform/minimal-observability-v3/profile.json"
        self.apps_path = HARNESS_DIR / "profiles/platform/minimal-observability-v3/applications.yaml"
        self.values_path = HARNESS_DIR / "profiles/platform/minimal-observability-v3/provider-values.yaml"
        self.profile = json.loads(self.profile_path.read_text())
        self.apps = [item for item in yaml.safe_load_all(self.apps_path.read_text()) if item]
        self.values = PLATFORM.V1.read_yaml_or_json(self.values_path)
        self.fixture = json.loads((HARNESS_DIR / "fixtures/execution/phase-r-v3.json").read_text())

    def validate(self, profile=None, apps=None, values=None):
        return PLATFORM.validate_platform_amendment(
            profile if profile is not None else self.profile,
            apps if apps is not None else self.apps,
            values if values is not None else self.values,
        )

    def test_identical_semantic_inputs_reproduce_p_double_prime(self):
        self.assertEqual(self.validate(), self.fixture["platform"]["P"])
        self.assertEqual(self.validate(copy.deepcopy(self.profile), copy.deepcopy(self.apps), copy.deepcopy(self.values)), self.fixture["platform"]["P"])

    def test_provider_value_change_changes_identity_and_fails_old_profile(self):
        changed = copy.deepcopy(self.values)
        changed["ok-observability-prometheus"]["kube-prometheus-stack"]["prometheus"]["prometheusSpec"]["retention"] = "7d"
        self.assertNotEqual(PLATFORM.V1.semantic_revision(changed), self.profile["providerValues"]["digest"])
        with self.assertRaises(PLATFORM.V1.HarnessError):
            self.validate(values=changed)

    def test_required_application_added_or_removed_fails_closed(self):
        with self.assertRaises(PLATFORM.V1.HarnessError):
            self.validate(apps=self.apps[:-1])
        extra = copy.deepcopy(self.apps[0])
        extra["metadata"]["name"] = "implicit-extra-child"
        with self.assertRaises(PLATFORM.V1.HarnessError):
            self.validate(apps=self.apps + [extra])

    def test_namespace_or_security_change_changes_p_and_breaks_projection(self):
        changed = copy.deepcopy(self.profile)
        changed["namespace"]["podSecurityLabels"]["pod-security.kubernetes.io/enforce"] = "baseline"
        self.assertNotEqual(PLATFORM.V1.semantic_revision(changed), self.fixture["platform"]["P"])
        with self.assertRaises(PLATFORM.V1.HarnessError):
            self.validate(profile=changed)

    def test_target_identity_change_changes_p(self):
        changed = copy.deepcopy(self.profile)
        ref = {"namespace": "disposable-ok141", "name": "different-incarnation-contract"}
        changed["target"]["contractIdentity"] = ref
        changed["target"]["immutableIdentityReference"]["contractRef"] = ref
        self.assertNotEqual(PLATFORM.V1.semantic_revision(changed), self.fixture["platform"]["P"])

    def test_mutable_source_revision_fails_closed(self):
        changed = copy.deepcopy(self.apps)
        changed[0]["spec"]["source"]["targetRevision"] = "main"
        with self.assertRaises(PLATFORM.V1.HarnessError):
            self.validate(apps=changed)

    def test_all_pinned_source_artifacts_exist_and_match_when_sibling_is_available(self):
        source = HARNESS_DIR.parents[3].parent / "ok-observability"
        if not (source / ".git").is_dir():
            self.skipTest("ok-observability sibling source is not available")
        for leaf in self.profile["requiredApplications"]:
            commit = leaf["source"]["commit"]
            subprocess.run(["git", "-C", str(source), "cat-file", "-e", f"{commit}^{{commit}}"], check=True)
            artifact_paths = {
                "chartDigest": f"{leaf['source']['path']}/Chart.yaml",
                "defaultValuesDigest": f"{leaf['source']['path']}/values.yaml",
                "manifestDigest": f"{leaf['source']['path']}/{leaf['source'].get('include', '')}",
            }
            for key, digest in leaf["sourceArtifacts"].items():
                raw = subprocess.run(
                    ["git", "-C", str(source), "show", f"{commit}:{artifact_paths[key]}"],
                    check=True, capture_output=True,
                ).stdout
                self.assertEqual(PLATFORM.V1.sha256_bytes(raw), digest)
        capability = self.profile["capabilityCheck"]
        for claim in (capability["contract"], capability["executable"]):
            raw = subprocess.run(
                ["git", "-C", str(source), "show", f"{self.profile['requiredApplications'][0]['source']['commit']}:{claim['path']}"],
                check=True, capture_output=True,
            ).stdout
            self.assertEqual(PLATFORM.V1.sha256_bytes(raw), claim["digest"])

    def test_phase_r_v3_reproduces_and_v2_remains_historical(self):
        self.assertEqual(PHASE.validate(self.fixture, HARNESS_DIR), self.fixture["fixtureDigest"])
        v2 = json.loads((HARNESS_DIR / "fixtures/execution/phase-r-v2.json").read_text())
        self.assertEqual(PHASE.V2.validate_execution_fixture_v2(v2, HARNESS_DIR), v2["fixtureDigest"])
        self.assertEqual(self.fixture["supersedes"]["fixtureDigest"], v2["fixtureDigest"])


if __name__ == "__main__":
    unittest.main()
