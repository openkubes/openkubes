"""Local-only OK AI gateway harness: no A2A, Ollama, MCP HTTP, or public use.

Every request retrieves source metadata independently from the validated local
index, then runs the answer gate. This is a *static response fixture*, not AI.
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from answer_integrity import validate_answer
from docs_mcp import DocsRetriever, load_index

MAX_REQUEST_BYTES = 4096


class Gateway:
    def __init__(self, index: dict, generator=None):
        self.index = index
        self.retriever = DocsRetriever(index)
        self.generator = generator or self._sample_generator

    @staticmethod
    def _sample_generator(question: str, hits: dict) -> str:
        # Explicitly NOT a model. The response deliberately avoids factual
        # prose, code, and inferred steps from the documents.
        first = hits["results"][0]
        return (
            "This is a static gateway test response, NOT a live AI answer. "
            "Read the source documentation here: "
            f"[OpenKubes documentation]({first['url']})"
        )

    def ask(self, question: object) -> tuple[int, dict]:
        if not isinstance(question, str) or not question.strip() or len(question) > 500:
            return 400, {"error": "invalid_question"}
        try:
            # Same-question retrieval is performed inside the gateway, not
            # supplied by the browser or claimed by the model.
            hits = self.retriever.docs_search(question, limit=8)
            if not hits["results"]:
                return 422, {"error": "no_verified_source"}
            answer = self.generator(question, hits)
            verdict = validate_answer(answer, hits, self.index)
            if not verdict.accepted:
                return 422, {"error": "answer_rejected", "reasons": list(verdict.reasons)}
            return 200, {
                "answer": answer,
                "demo": True,
                "sources": [{"source_id": h["source_id"], "url": h["url"]}
                            for h in hits["results"]],
            }
        except (ValueError, TypeError, KeyError):
            return 422, {"error": "invalid_retrieval"}


def make_handler(gateway: Gateway):
    class Handler(BaseHTTPRequestHandler):
        def _reply(self, status: int, payload: dict):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/healthz":
                self._reply(200, {"status": "local-demo-only"})
            else:
                self._reply(404, {"error": "not_found"})

        def do_POST(self):
            if self.path != "/api/chat":
                self._reply(404, {"error": "not_found"})
                return
            try:
                size = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                size = -1
            if size < 0 or size > MAX_REQUEST_BYTES:
                self._reply(413, {"error": "invalid_request_size"})
                return
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                self._reply(415, {"error": "unsupported_media_type"})
                return
            try:
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict) or set(body) != {"question"}:
                    raise ValueError("Expected only question")
            except (ValueError, UnicodeDecodeError):
                self._reply(400, {"error": "invalid_json"})
                return
            status, response = gateway.ask(body["question"])
            self._reply(status, response)

        def log_message(self, format, *args):
            # Do not emit question text or request paths to stdout.
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--port", type=int, default=18081)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Port must be between 1024 and 65535")
    gateway = Gateway(load_index(args.index))
    # Hardcoded loopback: not configurable to 0.0.0.0.
    with ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(gateway)) as server:
        server.daemon_threads = True
        print(f"OK AI static local gateway demo: http://127.0.0.1:{args.port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
