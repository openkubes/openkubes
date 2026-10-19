"""Local-only HTTP boundary for curated Beta 1 Lite (NOT public deployment).

Standard library only. Mandatory bearer token, exact loopback bind, bounded
JSON body, simple sliding-window rate limit and no question/answer access logs.
Do not publish this port or put a bearer token into browser JavaScript.
"""
from __future__ import annotations

import argparse
from collections import deque
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import time

from docs_mcp import load_index, validate_index
from public_beta.curated_lite import curated_answer

MAX_BODY_BYTES = 1024
WINDOW_SECONDS = 60
MAX_REQUESTS = 20
LOOPBACK = "127.0.0.1"


class SlidingWindowLimiter:
    def __init__(self, limit=MAX_REQUESTS, window=WINDOW_SECONDS, clock=None):
        self.limit = limit
        self.window = window
        self.clock = clock or time.monotonic
        self.events = deque()

    def allow(self):
        now = self.clock()
        while self.events and self.events[0] <= now - self.window:
            self.events.popleft()
        if len(self.events) >= self.limit:
            return False
        self.events.append(now)
        return True


def make_handler(index: dict, token: str, limiter=None):
    """Create one private HTTP handler; caller owns server lifetime."""
    if not isinstance(token, str) or len(token) < 32 or len(token) > 256:
        raise ValueError("beta_auth_token_invalid")
    verified = validate_index(index)
    rate = limiter or SlidingWindowLimiter()

    class CuratedLiteHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, format, *args):
            # Do not print URL query strings, headers, IPs or response bodies.
            pass

        def _reply(self, code, payload):
            raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            # No unauthenticated health or model/system introspection endpoint.
            self._reply(404, {"status": "NOT_FOUND"})

        def do_OPTIONS(self):
            self._reply(405, {"status": "METHOD_NOT_ALLOWED"})

        def do_POST(self):
            if self.path != "/api/beta1-lite/question":
                self._reply(404, {"status": "NOT_FOUND"})
                return
            supplied = self.headers.get("Authorization", "")
            if not supplied.startswith("Bearer ") or not hmac.compare_digest(
                    supplied[7:], token):
                self._reply(401, {"status": "UNAUTHORIZED"})
                return
            if not rate.allow():
                self._reply(429, {"status": "RATE_LIMITED"})
                return
            content_type = self.headers.get("Content-Type", "")
            if content_type.lower().strip() != "application/json":
                self._reply(415, {"status": "UNSUPPORTED_MEDIA_TYPE"})
                return
            length = self.headers.get("Content-Length")
            try:
                count = int(length) if length is not None else -1
            except (TypeError, ValueError):
                count = -1
            if not 1 <= count <= MAX_BODY_BYTES:
                self._reply(413, {"status": "INVALID_BODY_SIZE"})
                return
            try:
                raw = self.rfile.read(count)
                body = json.loads(raw)
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                self._reply(400, {"status": "INVALID_JSON"})
                return
            if not isinstance(body, dict) or set(body) != {"question"}:
                self._reply(400, {"status": "INVALID_REQUEST"})
                return
            question = body["question"]
            try:
                result = curated_answer(question, verified)
            except Exception:
                # Never expose internal exceptions, user input, or doc chunks.
                self._reply(503, {"status": "UNAVAILABLE"})
                return
            code = 200 if result["status"] in ("ANSWER", "UNSUPPORTED") else 503
            self._reply(code, result)

    return CuratedLiteHandler


def build_server(index, token, *, host=LOOPBACK, port=8765, limiter=None):
    if host != LOOPBACK:
        raise ValueError("loopback_only")
    server = HTTPServer((host, port), make_handler(index, token, limiter))
    server.timeout = 5
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    # Secret only via process environment; never log or print it.
    token = os.environ.get("OPENKUBES_BETA1_LITE_TOKEN", "")
    try:
        server = build_server(load_index(args.index), token, port=args.port)
    except Exception:
        raise SystemExit("STOP: private Lite server preflight failed") from None
    print("Private Beta 1 Lite HTTP ready on 127.0.0.1 (loopback only)")
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
