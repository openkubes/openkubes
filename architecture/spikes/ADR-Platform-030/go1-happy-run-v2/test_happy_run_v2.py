import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("happy2", HERE / "bounded_happy_run_v2.py")
happy2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(happy2)


class HappyRunV2Tests(unittest.TestCase):
    def test_candidate_is_no_go_and_additive(self):
        plan = happy2.plan()
        self.assertEqual(plan["authorization"], "NO-GO")
        self.assertEqual(plan["supersedes"], happy2.V1_CANDIDATE_DIGEST)

    def test_projection_removes_only_unowned_shared_plane(self):
        source = tempfile.NamedTemporaryFile("w", delete=False)
        json.dump({"spec": {"credentialIdentityDigests": {"ok-infra": "i", "ok-mgmt": "m", "ok-shared": "s"}, "result": "PASS"}}, source); source.close()
        destination = Path(source.name + ".projected")
        try:
            value = json.loads(happy2.project_preflight(Path(source.name), destination).read_text())
            self.assertEqual(value["spec"]["credentialIdentityDigests"], {"ok-infra": "i", "ok-mgmt": "m"})
            self.assertEqual(value["spec"]["sourceEvidenceDigest"], happy2.sha(Path(source.name)))
            self.assertEqual(value["spec"]["result"], "PASS")
        finally:
            Path(source.name).unlink(); destination.unlink()

    def test_projection_fails_on_unexpected_source_planes(self):
        source = tempfile.NamedTemporaryFile("w", delete=False)
        json.dump({"spec": {"credentialIdentityDigests": {"ok-infra": "i", "ok-mgmt": "m"}}}, source); source.close()
        destination = Path(source.name + ".projected")
        try:
            with self.assertRaises(happy2.HappyRunV2Error): happy2.project_preflight(Path(source.name), destination)
        finally: Path(source.name).unlink()


if __name__ == "__main__": unittest.main()
