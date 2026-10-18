"""Private read-only documentation fallback; no executable commands or model URLs.

Only gateway-controlled, pinned source URLs can be returned. This helper
does not change the existing structured-answer acceptance contract.
"""
from __future__ import annotations

import re
from docs_mcp import validate_index

GUIDE_REPO = "openkubes/ok-local"
GUIDE_PATH = "docs/tutorial-basic.md"
INSTALL = re.compile(r"\b(?:install|installation|setup|set[ -]?up)\b", re.I)
LOCAL = re.compile(r"\b(?:openkubes[\s-]+local|ok[\s-]+local)\b", re.I)
MAC = re.compile(r"\b(?:macos|mac[\s-]?os|mac)\b", re.I)


def reviewed_guide_fallback(question: str, retrieval: dict, index: dict) -> dict:
    """Offer metadata-only pinned guide reference for a narrow known topic.

    This is a candidate fallback, not a command-safe or release-approved
    answer. Caller must still enforce response handling and authorization.
    """
    if (not isinstance(question, str) or not isinstance(retrieval, dict)
            or not (INSTALL.search(question) and LOCAL.search(question)
                    and MAC.search(question))):
        return {"status": "NO_FALLBACK", "display_authorized": False}
    corpus = validate_index(index)["corpus"]
    by_id = {doc["source_id"]: doc for doc in corpus}
    hits = retrieval.get("results")
    if not isinstance(hits, list) or not 1 <= len(hits) <= 8:
        raise ValueError("Invalid retrieval count")
    revisions = set()
    matching_sources = 0
    seen = set()
    for hit in hits:
        if not isinstance(hit, dict):
            raise ValueError("Invalid retrieval hit")
        sid = hit.get("source_id")
        doc = by_id.get(sid)
        if doc is None or sid in seen:
            raise ValueError("Unknown or duplicate retrieval hit")
        seen.add(sid)
        for key, value in (
            ("snippet", doc["text"]), ("url", doc["url"]),
            ("title", doc["section"]), ("repo", doc["repo"]),
            ("path", doc["path"]), ("commit_sha", doc["revision"]),
        ):
            if hit.get(key) != value:
                raise ValueError("Forged retrieval hit")
        if doc["repo"] == GUIDE_REPO and doc["path"] == GUIDE_PATH:
            revisions.add(doc["revision"])
            matching_sources += 1
    if not matching_sources or len(revisions) != 1:
        return {"status": "NO_FALLBACK", "display_authorized": False}
    revision = next(iter(revisions))
    if any(doc["revision"] != revision for doc in corpus
           if doc["repo"] == GUIDE_REPO and doc["path"] == GUIDE_PATH):
        raise ValueError("Mixed guide revisions")
    return {
        "status": "GUIDE_REFERENCE_CANDIDATE",
        "message": (
            "I cannot provide executable installation commands in this "
            "documentation beta. The public OpenKubes Local macOS tutorial "
            "contains the installation instructions; review them before use."
        ),
        "guide_url": f"https://github.com/{GUIDE_REPO}/blob/{revision}/{GUIDE_PATH}",
        "source_revision": revision,
        "retrieved_guide_chunks": matching_sources,
        "display_authorized": False,
        "execution_authorized": False,
    }
