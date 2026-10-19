"""Beta 1 Lite: offline curated Q&A, no model call or command rendering.

This is a candidate *library*, NOT a public API or deployable service.
Answers are immutable human-curated text only when the exact supporting
quote is present in a verified pinned documentation chunk.
"""
from __future__ import annotations

import re

from docs_mcp import validate_index

MAX_QUESTION = 240
REPO = "openkubes/ok-local"
PATH = "docs/tutorial-basic.md"
REQUIRED_QUOTE = "OpenKubes provides a fully automated local dev environment (`ok-local`) and a production-ready stack on Hetzner bare metal (`ok-rke2`)."

# Curated statements are intentionally narrower than the full document.
# A citation alone never authorizes generative assertions.
QUESTIONS = {
    "what is openkubes local": (
        "OpenKubes Local (ok-local) is a fully automated local development environment provided by the OpenKubes project."
    ),
    "what is ok local": (
        "OpenKubes Local (ok-local) is a fully automated local development environment provided by the OpenKubes project."
    ),
    "what is ok-local": (
        "OpenKubes Local (ok-local) is a fully automated local development environment provided by the OpenKubes project."
    ),
    "does openkubes provide a local development environment": (
        "Yes. OpenKubes provides a fully automated local development environment called ok-local."
    ),
}

# Exact-match, no fuzzy or semantic intent classification; unknown questions
# must never silently fall back to a nearby approved answer.
def _normalize(question: str) -> str:
    if (not isinstance(question, str) or not 1 <= len(question) <= MAX_QUESTION
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in question)):
        return ""
    stripped = question.strip().lower()
    return re.sub(r"[?.!]$", "", re.sub(r"\s+", " ", stripped)).strip()


def curated_answer(question: str, index: dict) -> dict:
    """Only a vetted answer and immutable citation, otherwise safe refusal."""
    key = _normalize(question)
    if not key or key not in QUESTIONS:
        return {
            "status": "UNSUPPORTED", "answer": (
                "This beta only supports a small set of reviewed documentation "
                "questions. Please consult the official OpenKubes documentation."
            ), "sources": [], "generative": False,
        }
    corpus = validate_index(index)["corpus"]
    matching = [
        doc for doc in corpus
        if doc["repo"] == REPO and doc["path"] == PATH
        and REQUIRED_QUOTE in doc["text"]
    ]
    # Fail closed on missing, inconsistent or ambiguous evidence. Never
    # choose whichever match happens to arrive first.
    if len(matching) != 1:
        return {"status": "UNAVAILABLE", "answer": (
            "The reviewed documentation source is currently unavailable."
        ), "sources": [], "generative": False}
    doc = matching[0]
    return {
        "status": "ANSWER",
        "answer": QUESTIONS[key],
        "sources": [{
            "source_id": doc["source_id"], "url": doc["url"],
            "revision": doc["revision"],
        }],
        "generative": False,
    }
