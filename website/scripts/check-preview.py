#!/usr/bin/env python3
"""Minimal preview acceptance checks for existing homepage URLs and assets."""
from html.parser import HTMLParser
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / ".mkdocs-site"
LEGACY = ROOT / "docs" / "index.html"
ARTICLES = [
    "developer-workspace-blog-post",
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
    if 'class="ok-global-nav__brand ok-global-nav__brand--text"' not in html:
        raise SystemExit("Missing text-only homepage branding")
    if '<img src="/openkubes-logo.png"' in html.split('ok-global-nav__links',1)[0]:
        raise SystemExit("Unexpected logo image in shared homepage navigation")
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
            if section == "features" and 'ok-global-nav__brand--text' not in page_html:
                raise SystemExit("OpenKubes text brand missing from Material navigation")
            if "OpenKubes primary navigation" not in page_html:
                raise SystemExit(f"Shared navigation missing on {section}")
    if not (SITE / "assets" / "openkubes-theme.css").is_file():
        raise SystemExit("Shared Material theme asset missing")
    guide_path = SITE / "community" / "how-to-update-docs" / "index.html"
    if not guide_path.is_file():
        raise SystemExit("Missing community documentation contribution guide")
    if "How to update the docs" not in guide_path.read_text(encoding="utf-8"):
        raise SystemExit("Incomplete community contribution guide")
    # Guard the OK AI navigation and generated capability entry points.
    for ai_path in ("ai/index.html", "ai/open-webui/index.html",
                    "ai/openclaw/index.html", "ai/kagent-platform-diagnostics/index.html",
                    "ai/agentic-operations/index.html", "ai/ai-glossary-newbies/index.html",
                    "ai/ai-roadmap/index.html"):
        if not (SITE / ai_path).is_file():
            raise SystemExit(f"Missing OK AI page: {ai_path}")
    roadmap_html = (SITE / "ai" / "ai-roadmap" / "index.html").read_text(encoding="utf-8")
    for required in ("Documentation Assistant", "Read-only Diagnostics",
                     "Agentic Operations", "ok-ai-roadmap__card"):
        if required not in roadmap_html:
            raise SystemExit(f"OK AI roadmap missing required content: {required}")
    if roadmap_html.count('class="ok-ai-roadmap__card ') != 3:
        raise SystemExit("OK AI roadmap must render exactly three cards")
    glossary_html = (SITE / "ai" / "ai-glossary-newbies" / "index.html")
    if not glossary_html.is_file():
        raise SystemExit("Missing AI Glossary rendered page")
    glossary_text = glossary_html.read_text(encoding="utf-8")
    for heading in ("Stage 1", "Stage 2", "Stage 3", "Stage 4"):
        if heading not in glossary_text:
            raise SystemExit(f"AI Glossary incomplete: {heading}")
    ai_html = (SITE / "ai" / "index.html").read_text(encoding="utf-8")
    if "Open WebUI" not in ai_html or "OpenClaw" not in ai_html:
        raise SystemExit("OK AI overview incomplete")
    # Require all OK Observability pages in the generated preview.
    for observability_path in (
        "observability/index.html",
        "observability/stack/index.html",
        "observability/contract/index.html",
        "observability/installation/index.html",
    ):
        if not (SITE / observability_path).is_file():
            raise SystemExit(f"Missing OK Observability page: {observability_path}")
    observability_html = (SITE / "observability" / "index.html").read_text(encoding="utf-8")
    if "Observability Capability" not in observability_html or "Capability Contract" not in observability_html:
        raise SystemExit("OK Observability overview incomplete")
    # Ensure Developer Workspace pages are generated and linked in the new nav.
    for workspace_path in (
        "developer-workspace/index.html",
        "developer-workspace/architecture/index.html",
        "developer-workspace/coding-agents/index.html",
        "developer-workspace/status/index.html",
        "developer-workspace/tutorial/index.html",
    ):
        if not (SITE / workspace_path).is_file():
            raise SystemExit(f"Missing Developer Workspace page: {workspace_path}")
    workspace_html = (SITE / "developer-workspace" / "index.html").read_text(encoding="utf-8")
    if "Developer Workspace" not in workspace_html or "OpenCode" not in workspace_html:
        raise SystemExit("Developer Workspace overview incomplete")
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
    for source in (ROOT / "docs").rglob("*"):
        if source.is_file():
            relative = source.relative_to(ROOT / "docs")
            if relative.as_posix() in ("CNAME", "index.html"):
                continue
            target = SITE / relative
            if not target.is_file() or target.read_bytes() != source.read_bytes():
                missing.append("/" + relative.as_posix())
    if missing:
        raise SystemExit("Preview missing files/links: " + ", ".join(sorted(set(missing))))
    print(f"Homepage, media, {len(ARTICLES)} permalink articles, docs and search checks passed.")

if __name__ == "__main__":
    main()
