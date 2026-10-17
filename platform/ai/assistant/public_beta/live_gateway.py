"""LAB-ONLY live A2A gateway harness, bound to localhost. NEVER deploy publicly.

The gateway retrieves independent validated local documentation for the same
question, calls the private A2A agent through an operator-managed port-forward,
and rejects any answer failing the existing syntax/provenance validator.

Independent retrieval is NOT proof of the model's actual docs_search tool call.
A PASS is preliminary local evidence, NOT public-release authorization.
"""
from __future__ import annotations

import argparse
import json
import socket
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path

from docs_mcp import load_index
from public_beta.local_gateway import Gateway, make_handler
from public_beta.private_a2a_probe import query_agent

FALLBACK = "The documentation answer could not be verified. Please use the official OpenKubes documentation."


class LiveGateway(Gateway):
    def __init__(self, index: dict, agent=query_agent):
        super().__init__(index, generator=lambda question, hits: agent(question))

    def ask(self, question: object) -> tuple[int, dict]:
        try:
            status, result = super().ask(question)
        except (OSError, TimeoutError, socket.timeout, urllib.error.URLError,
                json.JSONDecodeError, UnicodeError):
            return 503, {"error": "agent_unavailable", "message": FALLBACK}

        # Do not output raw rejected model text, internal diagnostics or URLs.
        if status == 422 and result.get("error") == "answer_rejected":
            return 422, {"error": "answer_rejected", "message": FALLBACK}
        if status == 422 and result.get("error") == "invalid_retrieval":
            return 422, {"error": "invalid_retrieval", "message": FALLBACK}
        if status == 200:
            # Explicitly signal an AI result, never the inherited static demo.
            result["demo"] = False
            result["lab_only"] = True
            result["provenance"] = "independent_local_retrieval"
        return status, result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18082)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Port must be between 1024 and 65535")
    gateway = LiveGateway(load_index(args.index))
    # Hardcoded loopback. No ingress or remote binding option.
    with ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(gateway)) as server:
        server.daemon_threads = True
        print(f"OK AI PRIVATE A2A lab: http://127.0.0.1:{args.port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
