#!/usr/bin/env python3
"""TLS smart-HTTP Git and fixture endpoints for the OK-174 live proof."""
import hmac
import os
import ssl
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/workspace-fixture.git/"):
            return self.git_http_backend()
        if self.path == "/mcp":
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"fixture":"mcp"}\n')
        elif self.path == "/known-commit":
            self.send_response(200); self.end_headers(); self.wfile.write(open('/srv/git/KNOWN_COMMIT','rb').read())
        else:
            self.send_response(404); self.end_headers()
    def log_message(self, *_): pass

    def do_POST(self):
        if self.path.startswith("/workspace-fixture.git/"):
            return self.git_http_backend()
        self.send_response(404); self.end_headers()

    def git_http_backend(self):
        expected = "Bearer " + os.environ.get("GIT_AUTH_TOKEN", "")
        if not expected.removeprefix("Bearer ") or not hmac.compare_digest(self.headers.get("Authorization", ""), expected):
            self.send_response(401)
            self.send_header("WWW-Authenticate", "Bearer")
            self.end_headers()
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        env = {
            **os.environ,
            "GIT_PROJECT_ROOT": "/srv/git",
            "GIT_HTTP_EXPORT_ALL": "1",
            "PATH_INFO": self.path.split("?", 1)[0],
            "QUERY_STRING": self.path.partition("?")[2],
            "REQUEST_METHOD": self.command,
            "CONTENT_TYPE": self.headers.get("Content-Type", ""),
            "CONTENT_LENGTH": str(len(body)),
            "REMOTE_USER": "workspace",
        }
        result = subprocess.run(["git", "http-backend"], input=body, capture_output=True, env=env, check=True)
        headers, payload = result.stdout.split(b"\r\n\r\n", 1)
        status = 200
        response_headers = []
        for line in headers.decode("iso-8859-1").split("\r\n"):
            key, value = line.split(":", 1)
            if key.lower() == "status":
                status = int(value.strip().split(" ", 1)[0])
            else:
                response_headers.append((key, value.strip()))
        self.send_response(status)
        for key, value in response_headers:
            self.send_header(key, value)
        # GnuTLS in git rejects a body delimited only by connection close.
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

def serve(port): ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
mode = os.environ.get("FIXTURE_MODE", "git")
if mode in ("mcp", "denied"):
    serve(8081)
if mode != "git":
    raise SystemExit(f"unsupported FIXTURE_MODE: {mode}")
Thread(target=serve, args=(8080,), daemon=True).start()
cert = os.environ.get("GIT_TLS_CERT_FILE", "/var/run/ok174-git-tls/tls.crt")
key = os.environ.get("GIT_TLS_KEY_FILE", "/var/run/ok174-git-tls/tls.key")
if not (os.path.isfile(cert) and os.path.isfile(key)):
    raise SystemExit("GIT_TLS_CERT_FILE and GIT_TLS_KEY_FILE must name mounted TLS files")
https = ThreadingHTTPServer(("0.0.0.0", 8443), Handler)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(cert, key)
https.socket = context.wrap_socket(https.socket, server_side=True)
https.serve_forever()
