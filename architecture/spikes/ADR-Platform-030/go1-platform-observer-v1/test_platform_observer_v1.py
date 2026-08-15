import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("observer", HERE / "bounded_platform_observer_v1.py")
observer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observer)


class PlatformObserverTests(unittest.TestCase):
    def app(self, sync="Synced", health="Healthy", revision="b5f7be6a7ddab798f31f32197fcbb9e86a9798b6"):
        candidate = observer.validate_candidate()
        fixture = candidate["spec"]["fixture"]
        return {"metadata": {"name": candidate["spec"]["argo"]["applicationNames"][0], "uid": "u", "annotations": {"openkubes.io/intent-revision": fixture["R"], "openkubes.io/platform-revision": fixture["P"], "openkubes.io/execution-fixture": fixture["fixtureDigest"]}}, "status": {"sync": {"status": sync, "revision": revision}, "health": {"status": health}}}

    def test_candidate_is_no_go(self):
        self.assertEqual(observer.validate_candidate()["spec"]["authorization"]["decision"], "NO-GO")

    def test_current_application_is_ready(self):
        ready, detail = observer.application_ready(self.app(), observer.validate_candidate())
        self.assertTrue(ready); self.assertEqual(detail["health"], "Healthy")

    def test_stale_or_unhealthy_application_is_not_ready(self):
        self.assertFalse(observer.application_ready(self.app(revision="main"), observer.validate_candidate())[0])
        self.assertFalse(observer.application_ready(self.app(health="Degraded"), observer.validate_candidate())[0])

    def test_wrong_identity_fails_closed(self):
        value = self.app(); value["metadata"]["annotations"]["openkubes.io/execution-fixture"] = "wrong"
        with self.assertRaises(observer.PlatformObserverError): observer.application_ready(value, observer.validate_candidate())


if __name__ == "__main__": unittest.main()
