#!/usr/bin/env python3
"""Audit candidate public URLs without changing the existing website.

The legacy site was served by GitHub Pages; source Markdown may have had
Jekyll-generated HTML URLs. Those candidates must be confirmed with HTTP
tests before production release. JSON output is generated for reviewers.
"""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs"
SITE = ROOT / ".mkdocs-site"
REPORT = ROOT / ".mkdocs-site" / "url-compatibility-report.json"

REQUIRED = (
    "/",
    "/features/",
    "/getting-started/",
    "/architecture/",
    "/blog/",
    "/docs/",
    "/community/",
    "/agentic-operations-reference-architecture/",
    "/vault-secret-contract-blog-post/",
    "/the-contract-is-the-guardrail-blog-post/",
    "/openkubes-self-healing-blog-post/",
    "/openkubes-blog-post/",
    "/OpenKubes-Presentation.html",
    "/knowledge-graph-template.html",
    "/openkubes_knowledge_graph_force_layout.html",
    "/media/openkubes-hero-light.webm",
    "/media/openkubes-hero-light.mp4",
)

def present(url):
    path = url.lstrip("/")
    if not path or url.endswith("/"):
        path = path + "index.html"
    return (SITE / path).is_file()

def main():
    if not SITE.is_dir() or not SOURCE.is_dir():
        raise SystemExit("Run the site build and legacy URL restoration first")
    missing_required = [url for url in REQUIRED if not present(url)]
    missing_raw = []
    markdown_candidates = []
    missing_legacy_html = []
    for source in sorted(SOURCE.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(SOURCE)
        if relative.as_posix() == "CNAME":
            continue
        raw_url = "/" + relative.as_posix()
        if not present(raw_url):
            missing_raw.append(raw_url)
        if source.suffix.lower() == ".md":
            # GitHub Pages Jekyll may render .md as .html; cannot infer
            # front matter permalink overrides without a deployed-site crawl.
            candidate = "/" + relative.with_suffix(".html").as_posix()
            if not present(candidate):
                missing_legacy_html.append(candidate)
            markdown_candidates.append({
                "source": raw_url,
                "possible_legacy_html_url": candidate,
                "exists_in_candidate_build": present(candidate),
                "requires_live_url_verification": True,
            })
    report = {
        "required_paths": list(REQUIRED),
        "missing_required_paths": missing_required,
        "missing_source_file_paths": missing_raw,
        "missing_legacy_html_paths": missing_legacy_html,
        "markdown_html_candidates_to_verify": markdown_candidates,
        "production_cutover_approved": False,
        "notes": "File preservation does not prove parity with Jekyll-rendered URLs, redirects, fragments or third-party inbound links.",
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"URL audit: {len(REQUIRED)} required routes, {len(markdown_candidates)} Markdown/Jekyll candidates")
    print(f"Report: {REPORT}")
    if missing_required or missing_raw or missing_legacy_html:
        raise SystemExit(f"URL audit failed: {len(missing_required)} required, {len(missing_raw)} raw, {len(missing_legacy_html)} Jekyll HTML paths missing")

if __name__ == "__main__":
    main()
