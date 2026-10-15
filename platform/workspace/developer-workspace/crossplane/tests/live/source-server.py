#!/usr/bin/env python3
"""TLS smart-HTTP Git source with credential-scoped write authority (OK-175 live proof).

It stands in for a source provider that issues a workspace a read-only credential. The
workspace's token (GIT_READ_TOKEN) may fetch; only the harness-held GIT_WRITE_TOKEN may push.
A push with the read token is rejected with 403 before git-http-backend runs, so the
denial is the server's credential scope, not a missing repository setting. Mounted over the
OK-174 fixture image's server.py; that image's entrypoint creates the repository first.
On start the default branch moves one commit past KNOWN_COMMIT, so a checkout that ignored the
declared revision would land on a different commit.
"""
import hmac
import os
import ssl
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

READ = os.environ["GIT_READ_TOKEN"]
WRITE = os.environ["GIT_WRITE_TOKEN"]
REPO = "/workspace-fixture.git/"

def advance_default_branch():
    git = ["git", "--git-dir=/srv/git" + REPO.rstrip("/")]
    known = open("/srv/git/KNOWN_COMMIT").read().strip()
    if subprocess.run(git + ["rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip() != known:
        return
    tree = subprocess.run(git + ["rev-parse", known + "^{tree}"], capture_output=True, text=True, check=True).stdout.strip()
    stamp = {"GIT_AUTHOR_NAME": "OK-175 fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid", "GIT_AUTHOR_DATE": "2024-01-02T00:00:00Z",
             "GIT_COMMITTER_NAME": "OK-175 fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid", "GIT_COMMITTER_DATE": "2024-01-02T00:00:00Z"}
    tip = subprocess.run(git + ["commit-tree", tree, "-p", known, "-m", "newer tip"], capture_output=True, text=True, check=True, env={**os.environ, **stamp}).stdout.strip()
    branch = subprocess.run(git + ["symbolic-ref", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run(git + ["update-ref", branch, tip, known], check=True)

def matches(header, token):
    return bool(token) and hmac.compare_digest(header, "Bearer " + token)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith(REPO):
            return self.git()
        if self.path == "/known-commit":
            body = open("/srv/git/KNOWN_COMMIT", "rb").read()
            self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        else:
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers()

    def do_POST(self):
        if self.path.startswith(REPO):
            return self.git()
        self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers()

    def log_message(self, *_):
        pass

    def git(self):
        header = self.headers.get("Authorization", "")
        writer = matches(header, WRITE)
        if not (writer or matches(header, READ)):
            self.send_response(401); self.send_header("WWW-Authenticate", "Bearer"); self.send_header("Content-Length", "0"); self.end_headers()
            return
        push = "git-receive-pack" in self.path
        if push and not writer:
            body = b"read-only credential: push denied\n"
            self.send_response(403); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
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
        }
        if writer:
            env["REMOTE_USER"] = "writer"  # git-http-backend enables receive-pack only for an authenticated user
        result = subprocess.run(["git", "http-backend"], input=body, capture_output=True, env=env, check=True)
        headers, payload = result.stdout.split(b"\r\n\r\n", 1)
        status, response_headers = 200, []
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

advance_default_branch()
server = ThreadingHTTPServer(("0.0.0.0", 8443), Handler)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(os.environ["GIT_TLS_CERT_FILE"], os.environ["GIT_TLS_KEY_FILE"])
server.socket = context.wrap_socket(server.socket, server_side=True)
server.serve_forever()
