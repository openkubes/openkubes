#!/usr/bin/env python3
"""OK-202 read-only MCP retrieval adapter (local PoC, not a public service).

The MCP runtime is optional for unit tests. No Kubernetes or shell tools exist.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import quote

from indexer import SOURCES, search

SHA = re.compile(r"^[0-9a-f]{40}$")
HEX = re.compile(r"^[0-9a-f]{16}$")
MAX_CORPUS = 10000
MAX_CHUNK_CHARS = 2600


def validate_index(index: object) -> dict:
    """Fail closed if the index contains unknown sources or forged citations."""
    if not isinstance(index, dict) or index.get("schema_version") != 1:
        raise ValueError("Unsupported index schema")
    corpus = index.get("corpus")
    if not isinstance(corpus, list) or len(corpus) > MAX_CORPUS:
        raise ValueError("Invalid corpus")
    seen: set[str] = set()
    result = []
    for doc in corpus:
        if not isinstance(doc, dict):
            raise ValueError("Invalid document")
        source_id, repo, path, revision = (
            doc.get("source_id"), doc.get("repo"), doc.get("path"), doc.get("revision")
        )
        if not (isinstance(source_id, str) and HEX.fullmatch(source_id)
                and source_id not in seen):
            raise ValueError("Invalid or duplicate source ID")
        if not (isinstance(repo, str) and repo in SOURCES
                and isinstance(path, str) and path in SOURCES[repo]
                and isinstance(revision, str) and SHA.fullmatch(revision)):
            raise ValueError("Unapproved repository, path, or revision")
        text = doc.get("text")
        if not isinstance(text, str) or len(text) > MAX_CHUNK_CHARS:
            raise ValueError("Invalid chunk text")
        digest = doc.get("sha256")
        if not isinstance(digest, str) or hashlib.sha256(text.encode()).hexdigest() != digest:
            raise ValueError("Chunk integrity check failed")
        expected_id = hashlib.sha256(
            f"{repo}:{revision}:{path}:{doc.get('chunk_number', 'legacy')}".encode()
        ).hexdigest()[:16]
        # Older v1 indexes do not store chunk_number; source IDs must still be
        # unique and hex, but cannot be recomputed without that number.
        if "chunk_number" in doc and source_id != expected_id:
            raise ValueError("Chunk identity check failed")
        url = f"https://github.com/{repo}/blob/{revision}/{path}"
        if doc.get("url") != url:
            raise ValueError("Citation URL mismatch")
        seen.add(source_id)
        result.append(doc)
    return {"schema_version": 1, "corpus": result}


def load_index(filename: str | Path) -> dict:
    path = Path(filename)
    if path.stat().st_size > 30_000_000:
        raise ValueError("Index is too large")
    return validate_index(json.loads(path.read_text(encoding="utf-8")))


class DocsRetriever:
    """Immutable in-memory snapshot. Tool calls never perform network I/O."""

    def __init__(self, index: dict):
        self.index = validate_index(index)

    def docs_search(self, query: str, limit: int = 5) -> dict:
        hits = search(self.index, query, limit)
        return {"results": [
            {
                "source_id": hit["source_id"],
                "title": hit["section"],
                "snippet": hit["text"][:MAX_CHUNK_CHARS],
                "repo": hit["repo"],
                "path": hit["path"],
                "commit_sha": hit["revision"],
                "url": hit["url"],
            }
            for hit in hits
        ]}


def main() -> None:
    from mcp.server.fastmcp import FastMCP

    index_file = os.environ.get("OPENKUBES_DOCS_INDEX")
    if not index_file:
        raise SystemExit("OPENKUBES_DOCS_INDEX must point to a reviewed local index")
    retriever = DocsRetriever(load_index(index_file))
    host = os.environ.get("OPENKUBES_MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("OPENKUBES_MCP_PORT", "8000"))
    mcp = FastMCP(
        "OpenKubes public documentation",
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
    )

    @mcp.tool()
    def docs_search(query: str, limit: int = 5) -> dict:
        """Search only reviewed public OpenKubes documentation with pinned sources."""
        return retriever.docs_search(query, limit)

    transport = os.environ.get("OPENKUBES_MCP_TRANSPORT", "stdio")
    if transport not in ("stdio", "streamable-http"):
        raise SystemExit("Invalid transport")
    # HTTP may ONLY bind to a trusted loopback or internal interface; do not
    # expose port directly to public internet or the website.
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
