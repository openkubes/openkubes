"""PRIVATE lab probe for isolated JSON A2A agent. Not a public release gate.

The local retriever is independent of the agent's actual MCP calls.
A local PASS demonstrates contract syntax/index binding only, not semantics
or actual per-request MCP provenance.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from docs_mcp import DocsRetriever, load_index
from public_beta.private_a2a_probe import LAB_A2A_URL, query_agent
from public_beta.structured_answer import ContractRejected, validate_and_render


def run_structured_probe(index: dict, question: str, *, ask=None) -> dict:
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 500:
        return {"status": "ERROR", "error": "invalid_question"}
    hits = DocsRetriever(index).docs_search(question, limit=8)
    if not hits["results"]:
        return {"status": "NO_SOURCES", "accepted": False,
                "reason": "no_verified_source"}
    if ask is None:
        ask = lambda q: query_agent(q, agent_url=LAB_A2A_URL)
    response = ask(question)
    try:
        validated = validate_and_render(response, hits, index)
    except ContractRejected as exc:
        # Only the contract's fixed, code-defined reason strings are exposed.
        return {"status": "REJECT", "accepted": False,
                "reason": str(exc), "retrieved_chunks": len(hits)}
    return {"status": "PASS", "accepted": True,
            "rendered_chars": len(validated),
            "retrieved_chunks": len(hits),
            "warning": "Syntax and local index only; not actual MCP provenance or semantic truth"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--question", default="How do I install OpenKubes Local on macOS?")
    args = parser.parse_args()
    try:
        result = run_structured_probe(load_index(args.index), args.question)
    except (ValueError, TypeError, KeyError, OSError, TimeoutError,
            json.JSONDecodeError) as exc:
        # Never log raw agent replies or internal A2A targets.
        print(json.dumps({"status": "ERROR", "error_type": type(exc).__name__}))
        raise SystemExit(2) from None
    print(json.dumps(result, indent=2))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
