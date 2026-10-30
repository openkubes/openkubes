"""PRIVATE LAB ONLY: real kagent A2A behind loopback and a fail-closed gate.

Not production-ready. The gateway reconstructs retrieval locally; it cannot
prove what the remote agent actually saw in its MCP invocation. A validator
PASS is syntactic and not a guarantee of semantic correctness or command safety.
"""
from __future__ import annotations

import argparse
import json
import urllib.error
from http.server import HTTPServer
from pathlib import Path

from answer_integrity import validate_answer
from docs_mcp import load_index
from public_beta.local_gateway import Gateway, make_handler
from public_beta.private_a2a_probe import query_agent


class PrivateLiveGateway(Gateway):
    def __init__(self, index: dict, ask=None):
        super().__init__(index)
        self._ask = query_agent if ask is None else ask

    def ask(self, question: object) -> tuple[int, dict]:
        if not isinstance(question, str) or not question.strip() or len(question) > 500:
            return 400, {"error": "invalid_question"}
        try:
            # Locally reconstructed *same-question* retrieval is an additional
            # gate, NOT trusted attestation of the remote MCP tool invocation.
            hits = self.retriever.docs_search(question, limit=8)
            if not hits["results"]:
                return 422, {"error": "no_verified_source"}
            answer = self._ask(question)
            verdict = validate_answer(answer, hits, self.index)
            if not verdict.accepted:
                # Never disclose rejected model output or details to clients.
                return 422, {"error": "answer_rejected"}
            return 200, {
                "answer": answer,
                "lab_only": True,
                "source_urls": sorted({h["url"] for h in hits["results"]}),
            }
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return 502, {"error": "agent_unavailable"}
        except (TimeoutError, OSError, urllib.error.URLError):
            return 502, {"error": "agent_unavailable"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--port", default=18082, type=int)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Port must be between 1024 and 65535")
    gateway = PrivateLiveGateway(load_index(args.index))
    # Intentionally non-threaded and bound to literal loopback. A client can
    # never configure the bind address through CLI or HTTP.
    with HTTPServer(("127.0.0.1", args.port), make_handler(gateway)) as server:
        print("Private live A2A gateway LAB ONLY listening on 127.0.0.1:"
              + str(args.port), flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
