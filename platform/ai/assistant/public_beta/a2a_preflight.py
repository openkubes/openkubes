#!/usr/bin/env python3
"""Read-only local preflight for the OK AI documentation agent A2A card.

Requires an operator-managed localhost port-forward to the kagent controller.
Never connects to a public or arbitrary host, prints credentials, or invokes an agent.
"""
import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

PATH = "/api/a2a/openkubes-assistant/openkubes-docs-agent/.well-known/agent-card.json"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8083, help="Local forwarded port (default: 8083)")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be 1..65535")
    url = f"http://127.0.0.1:{args.port}{PATH}"
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with build_opener(NoRedirect).open(request, timeout=5) as response:
            if response.status != 200:
                raise ValueError(f"unexpected status {response.status}")
            if int(response.headers.get("Content-Length", "0")) > 65536:
                raise ValueError("agent card too large")
            payload = response.read(65537)
            if len(payload) > 65536:
                raise ValueError("agent card too large")
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        print(f"FAIL: A2A agent card unavailable on localhost: {type(exc).__name__}", file=sys.stderr)
        print("Check local port-forward and installed kagent API version; do not expose controller publicly.", file=sys.stderr)
        return 1
    try:
        card = json.loads(payload)
        if not isinstance(card, dict) or not isinstance(card.get("name"), str):
            raise ValueError("invalid agent card")
    except (ValueError, UnicodeDecodeError):
        print("FAIL: invalid A2A agent card", file=sys.stderr)
        return 1
    capabilities = card.get("capabilities") or {}
    if not isinstance(capabilities, dict):
        capabilities = {}
    print("PASS: docs agent A2A agent card reachable via localhost")
    print("Name:", card["name"])
    print("Streaming advertised:", capabilities.get("streaming", "unknown"))
    print("Protocol version:", card.get("protocolVersion", "not advertised"))
    print("NOTE: discovery only; does not prove authentication, invocation, citations or safe public exposure.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
