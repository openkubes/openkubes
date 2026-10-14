#!/usr/bin/env python3
"""OK-202 public-document lexical retrieval PoC, not a live service.

No external dependencies. Network only during 'build'; 'search' is offline.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

# Explicit reviewed public allowlist: no wildcard URLs and no private repositories.
SOURCES = {
    "openkubes/openkubes": [
        "platform/ai/README.md",
        "platform/ai/platform-diagnostics/README.md",
        "docs/agentic-operations-reference-architecture.md",
    ],
    "openkubes/ok-local": [
        "docs/tutorial-basic.md",
        "docs/tutorial-capi.md",
    ],
}
TOKEN = re.compile(r"[a-z0-9][a-z0-9_-]{1,}", re.I)
MAX_BYTES = 300_000
MAX_RESULTS = 8


def fetch_text(url: str) -> str:
    # The caller constructs URLs exclusively from the fixed repository allowlist.
    request = urllib.request.Request(url, headers={"User-Agent": "openkubes-docs-poc/0.1"})
    with urllib.request.urlopen(request, timeout=15) as response:
        if response.geturl().split("/")[2] not in ("api.github.com", "raw.githubusercontent.com"):
            raise ValueError("Unexpected redirect destination")
        content = response.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise ValueError("Document exceeds size limit")
    return content.decode("utf-8")


def tokenize(value: str) -> Counter[str]:
    return Counter(TOKEN.findall(value.lower()))



CHUNK_TARGET = 2400
CHUNK_MAX = 2600
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def split_markdown(markdown: str) -> list[tuple[str, str]]:
    """Section-aware chunks preserving whole fenced code blocks.

    Reject oversized atomic paragraphs or code blocks instead of returning
    truncated or syntactically invalid shell commands.
    """
    output: list[tuple[str, str]] = []
    title = "Overview"
    lines: list[str] = []
    fence_char = ""
    fence_width = 0

    def flush() -> None:
        if not lines:
            return
        units: list[str] = []
        pending: list[str] = []
        current_fence = ""
        current_width = 0
        for line in lines:
            match = FENCE.match(line)
            if current_fence:
                pending.append(line)
                if (match and match.group(1)[0] == current_fence
                        and len(match.group(1)) >= current_width
                        and not match.group(2).strip()):
                    units.append("\n".join(pending))
                    pending = []
                    current_fence = ""
            elif match:
                if pending:
                    units.append("\n".join(pending).strip())
                    pending = []
                current_fence = match.group(1)[0]
                current_width = len(match.group(1))
                pending.append(line)
            elif not line.strip():
                if pending:
                    units.append("\n".join(pending).strip())
                    pending = []
            else:
                pending.append(line)
        if current_fence:
            raise ValueError("Unclosed fenced block in " + title)
        if pending:
            units.append("\n".join(pending).strip())

        chunk = ""
        for unit in units:
            if len(unit) > CHUNK_MAX:
                raise ValueError("Oversized atomic Markdown block in " + title)
            joined = chunk + "\n\n" + unit if chunk else unit
            if chunk and len(joined) > CHUNK_TARGET:
                output.append((title, chunk))
                chunk = unit
            else:
                chunk = joined
        if chunk:
            output.append((title, chunk))

    for line in markdown.splitlines():
        match = FENCE.match(line)
        was_inside = bool(fence_char)
        if match:
            if not fence_char:
                fence_char = match.group(1)[0]
                fence_width = len(match.group(1))
            elif (match.group(1)[0] == fence_char
                  and len(match.group(1)) >= fence_width
                  and not match.group(2).strip()):
                fence_char = ""
                fence_width = 0
        if not was_inside and not match and re.match(r"^#{1,4}\s+", line):
            flush()
            lines = []
            title = line.lstrip("# ").strip()[:160]
        else:
            lines.append(line)
    if fence_char:
        raise ValueError("Unclosed fenced block in " + title)
    flush()
    return output


def build_index(fetch=fetch_text) -> dict[str, Any]:
    docs: list[dict[str, str]] = []
    for repo, paths in SOURCES.items():
        owner, name = repo.split("/")
        response = json.loads(fetch(f"https://api.github.com/repos/{owner}/{name}/commits/main"))
        revision = response["sha"]
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("Invalid commit hash")
        for path in paths:
            if not re.fullmatch(r"[a-zA-Z0-9_./-]+", path) or ".." in path.split("/"):
                raise ValueError("Unsafe allowlist path")
            text = fetch(f"https://raw.githubusercontent.com/{repo}/{revision}/{path}")
            for n, (section, passage) in enumerate(split_markdown(text)):
                source_id = hashlib.sha256(f"{repo}:{revision}:{path}:{n}".encode()).hexdigest()[:16]
                docs.append({
                    "source_id": source_id,
                    "repo": repo,
                    "path": path,
                    "revision": revision,
                    "section": section,
                    "url": f"https://github.com/{repo}/blob/{revision}/{path}",
                    "sha256": hashlib.sha256(passage.encode()).hexdigest(),
                    "text": passage,
                })
    return {"schema_version": 1, "corpus": docs}


# Small, explainable relevance rules for the PoC (not an embedding replacement).
# Avoid generic English question words dominating long architecture sections.
STOPWORDS = frozenset({"how", "do", "i", "the", "a", "an", "to", "for",
                       "of", "is", "are", "we", "can", "my", "with", "and",
                       "in", "on", "what", "does"})
INSTALL_TERMS = frozenset({"install", "installation", "setup", "set-up", "start",
                           "quickstart", "deploy", "deployment", "getting-started"})


def search(index: dict[str, Any], query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Offline lexical search with explicit metadata/installation-intent boosts."""
    if not isinstance(query, str) or not query.strip() or len(query) > 4000:
        raise ValueError("Query must be 1-4000 characters")
    if not 1 <= limit <= MAX_RESULTS:
        raise ValueError("limit must be between 1 and 8")
    terms = set(tokenize(query)) - STOPWORDS
    if not terms:
        return []
    install_intent = bool(terms & INSTALL_TERMS)
    scored = []
    for doc in index["corpus"]:
        # Repository names and filenames matter as much as passage words.
        repo_terms = set(tokenize(doc["repo"]))
        path_terms = set(tokenize(doc["path"].replace("/", " ")))
        section_terms = set(tokenize(doc["section"]))
        content_terms = set(tokenize(doc["text"]))
        document_terms = repo_terms | path_terms | section_terms | content_terms
        if not terms & document_terms:
            continue
        # Presence, not raw frequency: long documents shouldn't win by length.
        score = (sum(2 for term in terms if term in content_terms)
                 + sum(4 for term in terms if term in section_terms)
                 + sum(5 for term in terms if term in path_terms)
                 + sum(8 for term in terms if term in repo_terms))
        # Install intent prefers an actual setup tutorial within a matched topic.
        topical_terms = terms - INSTALL_TERMS
        topic_match = bool(topical_terms & (repo_terms | path_terms | section_terms))
        if install_intent and topic_match:
            if "tutorial" in doc["path"] or "getting-started" in doc["path"]:
                score += 9
            if section_terms & INSTALL_TERMS:
                score += 5
        scored.append((score, doc["source_id"], doc))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [
        {k: doc[k] for k in ("source_id", "repo", "path", "revision", "section", "url", "text")}
        for _, _, doc in scored[:limit]
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    build = sub.add_parser("build")
    build.add_argument("--output", required=True)
    find = sub.add_parser("search")
    find.add_argument("--index", required=True)
    find.add_argument("--query", required=True)
    find.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    if args.cmd == "build":
        artifact = build_index()
        Path(args.output).write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
        print(f"Indexed {len(artifact['corpus'])} chunks -> {args.output}")
    else:
        index = json.loads(Path(args.index).read_text(encoding="utf-8"))
        print(json.dumps(search(index, args.query, args.limit), indent=2))


if __name__ == "__main__":
    main()
