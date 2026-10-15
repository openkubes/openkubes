"""Private OK AI A2A answer integrity probe. Localhost only; never public.

Invokes the existing kagent A2A docs agent via a *pre-established* kubectl
port-forward, then validates its generated answer against independently
retrieved, same-question local documentation. A rejection is useful evidence.
"""
from __future__ import annotations

import argparse
import json
import uuid
import urllib.error
import urllib.request
from pathlib import Path

from answer_integrity import validate_answer
from docs_mcp import DocsRetriever, load_index

A2A_URL = "http://127.0.0.1:8083/api/a2a/openkubes-assistant/openkubes-docs-agent/"
MAX_RESPONSE_BYTES = 256 * 1024
DEFAULT_QUESTION = "How do I install OpenKubes Local on macOS?"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("A2A redirects are forbidden")


def extract_answer(payload: object) -> str:
    """Extract textual artifact parts from a completed A2A JSON-RPC task."""
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        raise ValueError("Invalid A2A JSON-RPC response")
    if payload.get("error"):
        raise ValueError("A2A returned an error")
    task = payload.get("result")
    if not isinstance(task, dict) or task.get("kind") != "task":
        raise ValueError("Expected A2A task")
    status = task.get("status")
    if not isinstance(status, dict) or status.get("state") != "completed":
        raise ValueError("A2A task did not complete")
    blocks = []
    artifacts = task.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("No A2A artifacts")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ValueError("Invalid artifact")
        parts = artifact.get("parts")
        if not isinstance(parts, list):
            raise ValueError("Invalid artifact parts")
        for part in parts:
            if isinstance(part, dict) and part.get("kind") == "text":
                text = part.get("text")
                if not isinstance(text, str):
                    raise ValueError("Invalid text artifact")
                blocks.append(text)
    if not blocks or not any(b.strip() for b in blocks):
        raise ValueError("No answer text in completed A2A task")
    return "\n\n".join(blocks)


def query_agent(question: str, timeout: int = 90) -> str:
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 500:
        raise ValueError("Question must be 1-500 characters")
    request = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "kind": "message",
                "role": "user",
                "messageId": str(uuid.uuid4()),
                "parts": [{"kind": "text", "text": question}],
            },
            "configuration": {"blocking": True},
        },
    }
    req = urllib.request.Request(
        A2A_URL, data=json.dumps(request).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(req, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError("Unexpected A2A status")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("A2A response exceeds bound")
    return extract_answer(json.loads(raw))


def run_probe(index: dict, question: str, ask=query_agent):
    # Metadata must come from the local, validated snapshot, NOT A2A text.
    hits = DocsRetriever(index).docs_search(question, limit=8)
    if not hits["results"]:
        return {"status": "NO_SOURCES", "accepted": False, "reasons": ["no_verified_source"]}
    answer = ask(question)
    verdict = validate_answer(answer, hits, index)
    return {
        "status": "PASS" if verdict.accepted else "REJECT",
        "accepted": verdict.accepted,
        "reasons": list(verdict.reasons),
        "retrieved_chunks": len(hits["results"]),
        "answer_chars": len(answer),
        "source_ids": [hit["source_id"] for hit in hits["results"]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    args = parser.parse_args()
    try:
        result = run_probe(load_index(args.index), args.question)
    except (ValueError, OSError, TimeoutError, json.JSONDecodeError) as exc:
        # Avoid dumping raw model messages and internal URLs.
        print(json.dumps({"status": "ERROR", "error_type": type(exc).__name__}))
        raise SystemExit(2) from None
    print(json.dumps(result, indent=2))
    # A rejected LLM answer is a *failing* quality gate, even though the probe
    # itself successfully reached the private agent.
    if not result["accepted"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
