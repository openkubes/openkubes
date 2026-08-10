import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("live_observer_test", HERE / "live_observer.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class LiveObserverTests(unittest.TestCase):
    def test_command_surface_contains_only_get(self):
        self.assertTrue(MODULE.READS)
        self.assertTrue(all(command[0] == "get" for command in MODULE.READS.values()))
        self.assertEqual(set(MODULE.PLANES), {"ok-mgmt", "ok-shared"})

    def test_non_read_command_is_rejected_before_runner(self):
        called = []

        def runner(*args, **kwargs):
            called.append((args, kwargs))

        with self.assertRaises(MODULE.ObservationError):
            MODULE._run_json(Path("unused"), ("apply", "-f", "anything"), runner)
        self.assertEqual(called, [])

    def test_read_uses_explicit_kubeconfig_and_no_shell(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, json.dumps({"items": []}), "")

        result = MODULE._run_json(Path("/tmp/synthetic.yaml"), ("get", "nodes", "-o", "json"), runner)
        self.assertEqual(result, {"items": []})
        self.assertEqual(calls[0][0], ["kubectl", "--kubeconfig", "/tmp/synthetic.yaml", "get", "nodes", "-o", "json"])
        self.assertNotIsInstance(calls[0][0], str)
        self.assertTrue(calls[0][1]["check"])

    def test_quantity_conversion_is_deterministic(self):
        self.assertEqual(MODULE._cpu_milli("250m"), 250)
        self.assertEqual(MODULE._cpu_milli("2"), 2000)
        self.assertEqual(MODULE._memory_bytes("1Gi"), 1073741824)
        self.assertEqual(MODULE._memory_bytes("500Mi"), 524288000)


if __name__ == "__main__":
    unittest.main()
