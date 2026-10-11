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
    html = index.read_text(encoding="utf-8")
    original = LEGACY.read_text(encoding="utf-8")
    if "ok-global-nav" not in html or "OpenKubes primary navigation" not in html:
        raise SystemExit("Missing shared homepage navigation")
    for href in ("/", "/features/", "/architecture/", "/blog/", "/docs/", "/community/"):
        if f'href="{href}"' not in html:
            raise SystemExit(f"Navigation link missing: {href}")
    for asset in ("media/openkubes-hero-light.webm", "media/openkubes-hero-light.mp4", "media/openkubes-hero-light-poster.webp"):
        if asset not in html or asset not in original:
            raise SystemExit(f"Hero media reference lost: {asset}")
    if not (SITE / "assets" / "openkubes-navigation.css").is_file():
        raise SystemExit("Shared brand stylesheet missing")
    for section in ("features", "architecture", "blog", "community", "docs"):
        output = SITE / section / "index.html"
        if output.is_file():
            page_html = output.read_text(encoding="utf-8")
            if section == "features" and '/assets/openkubes-header-logo.png' not in page_html:
                raise SystemExit("Explicit logo missing from Material navigation")
            if "OpenKubes primary navigation" not in page_html:
                raise SystemExit(f"Shared navigation missing on {section}")
    if not (SITE / "assets" / "openkubes-header-logo.png").is_file():
        raise SystemExit("Optimized header logo missing from output")
    if not (SITE / "assets" / "openkubes-theme.css").is_file():
        raise SystemExit("Shared Material theme asset missing")
    parser = Refs()
    parser.feed(html)
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
    for section in ("features", "architecture", "blog", "community"):
        if not (SITE / section / "index.html").is_file():
            missing.append("/" + section + "/")
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
