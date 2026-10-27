import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_registration_diag_test", HERE / "bounded_registration_integrity_diagnostic_v1.py")
DIAG = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DIAG
assert SPEC.loader is not None
SPEC.loader.exec_module(DIAG)


class RegistrationIntegrityTests(unittest.TestCase):
    def test_candidate_is_inert(self):
        candidate = DIAG.validate_candidate()
        self.assertEqual(candidate["spec"]["authorization"]["decision"], "NO-GO")

    def test_template_is_no_go(self):
        value = yaml.safe_load((HERE / "registration-integrity-diagnostic-grant-v1.template.yaml").read_text())
        self.assertEqual(value["spec"]["decision"], "NO-GO")
        self.assertTrue(all(not item for key, item in value["spec"].items() if key.endswith("Granted")))

    def test_jwt_payload_decode_does_not_retain_token(self):
        payload = base64url(json.dumps({"sub": "subject", "aud": ["audience"], "exp": 9999999999}).encode())
        token = f"{base64url(b'header')}.{payload}.signature"
        decoded = DIAG.decode_jwt_payload(token)
        self.assertEqual(decoded["sub"], "subject")
        self.assertNotIn(token, json.dumps(decoded))

    def test_authority_sets_are_disjoint(self):
        self.assertFalse(set(DIAG.TRUE) & set(DIAG.FALSE))
        self.assertIn("mutationGranted", DIAG.FALSE)
        self.assertIn("happyRunResumeGranted", DIAG.FALSE)

    def test_raw_get_is_exact_and_read_only(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, b'{"kind":"Namespace"}', b"")

        result = DIAG.raw_get(Path("/private/tmp/kubectl"), Path("/private/tmp/kubeconfig"), "/api/v1/namespaces/ok-observability", runner)
        self.assertEqual(result[0], 0)
        self.assertEqual(calls[0][0], ["/private/tmp/kubectl", "--kubeconfig", "/private/tmp/kubeconfig", "get", "--raw", "/api/v1/namespaces/ok-observability"])
        self.assertFalse(calls[0][1]["check"])

    def test_exclusive_materialization_is_0600(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credential.yaml"
            DIAG.write_exclusive(path, b"secret")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                DIAG.write_exclusive(path, b"replacement")

    def test_failed_registration_cannot_materialize_or_contact_target(self):
        calls = []

        def runner(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("target runner must not be called")

        with tempfile.TemporaryDirectory() as directory:
            ephemeral = Path(directory) / "target.yaml"
            result = DIAG.probe_target(
                False, Path("/private/tmp/kubectl"), ephemeral,
                "/api/v1/namespaces/ok-observability", "https://target.invalid",
                "ca", "token", runner,
            )
            self.assertEqual(result, (-1, b"", b"", False))
            self.assertFalse(ephemeral.exists())
            self.assertEqual(calls, [])

    def test_successful_probe_removes_temporary_kubeconfig(self):
        with tempfile.TemporaryDirectory() as directory:
            ephemeral = Path(directory) / "target.yaml"

            def runner(command, **kwargs):
                self.assertTrue(ephemeral.is_file())
                self.assertEqual(ephemeral.stat().st_mode & 0o777, 0o600)
                return subprocess.CompletedProcess(command, 0, b'{"kind":"Namespace"}', b"")

            result = DIAG.probe_target(
                True, Path("/private/tmp/kubectl"), ephemeral,
                "/api/v1/namespaces/ok-observability", "https://target.invalid",
                "ca", "token", runner,
            )
            self.assertEqual(result, (0, b'{"kind":"Namespace"}', b"", True))
            self.assertFalse(ephemeral.exists())

    def test_publication_scope_is_redacted_and_bound(self):
        publication = yaml.safe_load((HERE / "publication-candidate-v1.yaml").read_text())
        self.assertEqual(publication["spec"]["decision"], "BLOCKED-NO-PUBLICATION")
        self.assertIn("private Evidence under /private/tmp", publication["spec"]["excludes"])
        for name, digest in publication["spec"]["scope"]["files"].items():
            if name != "test_registration_integrity_diagnostic_v1.py":
                self.assertEqual(DIAG.sha(HERE / name), digest)


def base64url(raw):
    import base64
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


if __name__ == "__main__":
    unittest.main()
