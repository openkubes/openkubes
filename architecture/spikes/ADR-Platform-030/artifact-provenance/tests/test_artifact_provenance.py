import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPIKE = ROOT.parent
MODULE_SPEC = importlib.util.spec_from_file_location(
    "ok141_artifact_provenance", ROOT / "verify_artifact_provenance.py"
)
PROVENANCE = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(PROVENANCE)


class ArtifactProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.enablement = PROVENANCE.load(PROVENANCE.ENABLEMENT_LOCK)
        self.platform = PROVENANCE.load(PROVENANCE.PLATFORM_LOCK)

    def test_locks_validate_and_correlate_current_fixture(self):
        PROVENANCE.validate_lock(self.enablement)
        PROVENANCE.validate_lock(self.platform)
        PROVENANCE.verify_fixture_correlation(self.enablement, self.platform)
        PROVENANCE.verify_checkpoint()

    def test_enablement_content_graph_is_closed_but_not_authorized(self):
        self.assertEqual(self.enablement["closure"]["contentGraph"], "CLOSED")
        self.assertEqual(self.enablement["integrity"]["content"], "PROVEN")
        self.assertEqual(
            self.enablement["integrity"]["authenticity"], "CONFIGURABLE-NOT-VERIFIED"
        )
        self.assertEqual(self.enablement["consumer"]["addressMode"], "TAG-ONLY")
        self.assertFalse(self.enablement["consumer"]["digestEnforced"])
        self.assertFalse(PROVENANCE.authorization_ready(self.enablement))

    def test_platform_vendor_graph_is_candidate_not_current_authority(self):
        self.assertEqual(self.platform["closure"]["contentGraph"], "CANDIDATE-CLOSED")
        self.assertFalse(self.platform["closure"]["authoritative"])
        self.assertTrue(all(not root["inImmutableRoot"] for root in self.platform["roots"]))
        self.assertFalse(PROVENANCE.authorization_ready(self.platform))

    def test_authorization_requires_every_supply_chain_dimension(self):
        candidate = copy.deepcopy(self.enablement)
        candidate["integrity"]["authenticity"] = "PROVEN"
        candidate["closure"]["authoritative"] = True
        candidate["consumer"]["digestEnforced"] = True
        self.assertTrue(PROVENANCE.authorization_ready(candidate))
        for mutation in (
            lambda value: value["integrity"].__setitem__("content", "UNRESOLVED"),
            lambda value: value["integrity"].__setitem__("authenticity", "UNRESOLVED"),
            lambda value: value["closure"].__setitem__("contentGraph", "OPEN"),
            lambda value: value["closure"].__setitem__("authoritative", False),
            lambda value: value["consumer"].__setitem__("digestEnforced", False),
            lambda value: value["roots"][0].__setitem__("inImmutableRoot", False),
        ):
            changed = copy.deepcopy(candidate)
            mutation(changed)
            self.assertFalse(PROVENANCE.authorization_ready(changed))

    def test_unknown_or_malformed_lock_fields_fail(self):
        changed = copy.deepcopy(self.enablement)
        changed["implicitTrust"] = True
        with self.assertRaises(PROVENANCE.VerificationError):
            PROVENANCE.validate_lock(changed)
        changed = copy.deepcopy(self.enablement)
        changed["roots"][0]["contentDigest"] = "sha256:wrong"
        with self.assertRaises(PROVENANCE.VerificationError):
            PROVENANCE.validate_lock(changed)

    def test_local_enablement_artifact_matches_oci_content_layer(self):
        sibling = SPIKE.parents[3] / "ok-cluster"
        if not sibling.is_dir():
            self.skipTest("ok-cluster sibling is unavailable")
        PROVENANCE.verify_enablement_local(self.enablement, sibling)

    def test_three_vendored_wrappers_reproduce_exact_platform_render(self):
        sibling = SPIKE.parents[3] / "ok-observability"
        if not (sibling / ".git").is_dir():
            self.skipTest("ok-observability sibling is unavailable")
        self.assertEqual(
            PROVENANCE.prove_platform_vendor_candidate(self.platform, sibling),
            PROVENANCE.EXPECTED_PLATFORM_RENDER,
        )

    def test_tampered_vendor_digest_fails(self):
        sibling = SPIKE.parents[3] / "ok-observability"
        if not (sibling / ".git").is_dir():
            self.skipTest("ok-observability sibling is unavailable")
        changed = copy.deepcopy(self.platform)
        changed["roots"][0]["contentDigest"] = "sha256:" + "0" * 64
        with self.assertRaises(PROVENANCE.VerificationError):
            PROVENANCE.prove_platform_vendor_candidate(changed, sibling)


if __name__ == "__main__":
    unittest.main()
