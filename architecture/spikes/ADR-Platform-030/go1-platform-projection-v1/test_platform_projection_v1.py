import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("projection", HERE / "bounded_platform_projection_v1.py")
projection = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(projection)


class ProjectionTests(unittest.TestCase):
    def test_projection_is_exact_and_no_go(self):
        summary = projection.projection_summary()
        self.assertEqual(summary["targetAccess"]["objects"], 8)
        self.assertEqual(summary["controlPlane"]["objects"], 4)
        self.assertEqual(summary["totalPersistentObjects"], 14)
        self.assertEqual(summary["authorization"], "NO-GO")

    def test_all_projected_objects_carry_v5_identities(self):
        candidate = projection.validate_candidate()
        expected = candidate["spec"]["fixture"]
        for item in projection.target_access() + projection.control_plane():
            annotations = item["metadata"]["annotations"]
            self.assertEqual(annotations["openkubes.io/intent-revision"], expected["R"])
            self.assertEqual(annotations["openkubes.io/platform-revision"], expected["P"])
            self.assertEqual(annotations["openkubes.io/execution-fixture"], expected["fixtureDigest"])

    def test_secret_rejects_missing_or_short_value(self):
        with self.assertRaises(projection.ProjectionError):
            projection.credential_secret(projection.CANDIDATE, {"grafana-admin-user": "short"})

    def test_generated_secret_values_are_bounded(self):
        values = projection.generate_credentials()
        secret = projection.credential_secret(projection.CANDIDATE, values)
        self.assertEqual(set(secret["stringData"]), set(values))
        self.assertNotIn("password", projection.projection_summary())


if __name__ == "__main__":
    unittest.main()
