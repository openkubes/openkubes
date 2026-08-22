import json
import ssl
import subprocess
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.client import HTTPSConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

from app import (
    QUERY_PATH,
    ObservedStateProducer,
    ProducerConfig,
    TlsConfig,
    handler_for,
    server_tls_context,
)
from test_app import claim, claim_list


NOW = datetime(2026, 8, 22, 9, 0, tzinfo=timezone.utc)


def openssl(*arguments: str) -> None:
    subprocess.run(
        ["openssl", *arguments],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def issue_certificate(root: Path, name: str, ca_name: str, extended_usage: str, san: str = "") -> None:
    openssl("genrsa", "-out", str(root / f"{name}.key"), "2048")
    openssl(
        "req", "-new", "-key", str(root / f"{name}.key"),
        "-subj", f"/CN={name}", "-out", str(root / f"{name}.csr"),
    )
    extension = root / f"{name}.ext"
    lines = [f"extendedKeyUsage={extended_usage}"]
    if san:
        lines.append(f"subjectAltName={san}")
    extension.write_text("\n".join(lines) + "\n", encoding="utf-8")
    openssl(
        "x509", "-req", "-in", str(root / f"{name}.csr"),
        "-CA", str(root / f"{ca_name}.crt"), "-CAkey", str(root / f"{ca_name}.key"),
        "-CAcreateserial", "-days", "1", "-sha256", "-extfile", str(extension),
        "-out", str(root / f"{name}.crt"),
    )


def create_test_pki(root: Path) -> None:
    for ca_name in ("trusted-ca", "rogue-ca"):
        openssl("genrsa", "-out", str(root / f"{ca_name}.key"), "2048")
        openssl(
            "req", "-x509", "-new", "-key", str(root / f"{ca_name}.key"),
            "-sha256", "-days", "1", "-subj", f"/CN={ca_name}",
            "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign",
            "-out", str(root / f"{ca_name}.crt"),
        )
    issue_certificate(root, "localhost", "trusted-ca", "serverAuth", "DNS:localhost,IP:127.0.0.1")
    issue_certificate(root, "console-bff", "trusted-ca", "clientAuth", "URI:spiffe://openkubes.io/ns/openkubes-console/sa/ok-console-bff")
    issue_certificate(root, "other-client", "trusted-ca", "clientAuth", "URI:spiffe://openkubes.io/ns/openkubes-console/sa/other-client")
    issue_certificate(root, "wrong-purpose", "trusted-ca", "serverAuth")
    issue_certificate(root, "rogue-client", "rogue-ca", "clientAuth")


class MutualTlsBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary_directory.name)
        create_test_pki(cls.root)

        class Client:
            def list_cluster_claims(self, _namespace):
                return claim_list(claim())

        producer = ObservedStateProducer(Client(), ProducerConfig(), now=lambda: NOW)
        expected_identity = "spiffe://openkubes.io/ns/openkubes-console/sa/ok-console-bff"
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            handler_for(producer, expected_client_identity=expected_identity),
        )
        tls = TlsConfig(
            certificate_file=cls.root / "localhost.crt",
            private_key_file=cls.root / "localhost.key",
            client_ca_file=cls.root / "trusted-ca.crt",
            expected_client_identity=expected_identity,
        )
        cls.server.socket = server_tls_context(tls).wrap_socket(cls.server.socket, server_side=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.temporary_directory.cleanup()

    def context(self, identity: str | None = None) -> ssl.SSLContext:
        context = ssl.create_default_context(cafile=self.root / "trusted-ca.crt")
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        if identity:
            context.load_cert_chain(self.root / f"{identity}.crt", self.root / f"{identity}.key")
        return context

    def request(self, path: str, identity: str | None = None):
        connection = HTTPSConnection("localhost", self.server.server_port, context=self.context(identity), timeout=3)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            body = json.loads(response.read())
            return response, body
        finally:
            connection.close()

    def test_valid_console_identity_reaches_the_read_only_query(self):
        response, body = self.request(QUERY_PATH, "console-bff")

        self.assertEqual(response.status, 200)
        self.assertEqual(body["kind"], "ConsoleObservedState")

    def test_health_is_https_but_does_not_expose_or_require_identity(self):
        response, body = self.request("/healthz")

        self.assertEqual(response.status, 200)
        self.assertEqual(body, {"status": "ok"})

    def test_missing_identity_is_bounded_and_fail_closed(self):
        response, body = self.request(QUERY_PATH)

        self.assertEqual(response.status, 403)
        self.assertEqual(body, {"error": "workload_identity_required"})

    def test_a_trusted_but_different_workload_identity_is_denied(self):
        response, body = self.request(QUERY_PATH, "other-client")

        self.assertEqual(response.status, 403)
        self.assertEqual(body, {"error": "workload_identity_required"})

    def test_untrusted_and_wrong_purpose_identity_fail_the_handshake(self):
        for identity in ("rogue-client", "wrong-purpose"):
            with self.subTest(identity=identity), self.assertRaises((ssl.SSLError, ConnectionError)):
                self.request(QUERY_PATH, identity)


if __name__ == "__main__":
    unittest.main()
