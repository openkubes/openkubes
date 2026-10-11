#!/usr/bin/env python3
"""Minimal preview acceptance checks for existing homepage URLs and assets."""
from html.parser import HTMLParser
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / ".mkdocs-site"
LEGACY = ROOT / "docs" / "index.html"
ARTICLES = [
    "agentic-operations-reference-architecture",
    "vault-secret-contract-blog-post",
    "the-contract-is-the-guardrail-blog-post",
    "openkubes-self-healing-blog-post",
    "openkubes-blog-post",
]
class Refs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for key in ("src", "href", "poster"):
            if attrs.get(key):
                self.refs.append(attrs[key])

def main():
    index = SITE / "index.html"
    if index.read_bytes() != LEGACY.read_bytes():
        raise SystemExit("Homepage preservation failed.")
    parser = Refs()
    parser.feed(index.read_text(encoding="utf-8"))
    missing = []
    for href in parser.refs:
        href = href.split("#", 1)[0].split("?", 1)[0]
        if not href or href.startswith(("http:", "https:", "mailto:", "//", "data:")):
            continue
        if href.startswith("/"):
            # Only validate known legacy article URLs; other site routes are out of scope.
            if href.strip("/") in ARTICLES and not (SITE / href.strip("/") / "index.html").is_file():
                missing.append(href)
            continue
        path = (SITE / href).resolve()
        if not path.is_relative_to(SITE.resolve()) or not path.is_file():
            missing.append(href)
    for slug in ARTICLES:
        if not (SITE / slug / "index.html").is_file():
            missing.append("/" + slug + "/")
    for path in ("docs/index.html", "docs/ok-local/tutorial-prerequisites/index.html",
                 "docs/ok-cluster/registry-trust/index.html", "search/search_index.json"):
        if not (SITE / path).is_file():
            missing.append(path)
    if missing:
        raise SystemExit("Preview missing files/links: " + ", ".join(sorted(set(missing))))
    print("Homepage, media, five permalink articles, docs and search checks passed.")

if __name__ == "__main__":
    main()
