#!/usr/bin/env python3
"""Assert the MkDocs candidate can be hosted on the existing GitHub Pages domain."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / ".mkdocs-site"

def main():
    if (SITE / "CNAME").read_text(encoding="utf-8").strip() != "openkubes.org":
        raise SystemExit("GitHub Pages production CNAME is missing or incorrect")
    if not (SITE / ".nojekyll").is_file():
        raise SystemExit("GitHub Pages .nojekyll marker is missing")
    robots = (SITE / "robots.txt").read_text(encoding="utf-8")
    if "Disallow: /" in robots or "Allow: /" not in robots:
        raise SystemExit("Production must be publicly indexable")
    if (SITE / "_headers").exists():
        raise SystemExit("Preview-only Cloudflare _headers must not be shipped")
    for name in ("index.html", "getting-started/index.html",
                 "agentic-operations-reference-architecture/index.html",
                 "agentic-operations-reference-architecture.html",
                 "OpenKubes-Presentation.html", "search/search_index.json"):
        if not (SITE / name).is_file():
            raise SystemExit("Missing production candidate path: " + name)
    # Production launch guard: all pages must use the same reviewed Lite UI.
    homepage = (SITE / "index.html").read_text(encoding="utf-8")
    ai_page = (SITE / "ai" / "index.html").read_text(encoding="utf-8")
    widget = (SITE / "assets" / "ok-ai-lite-preview.js").read_text(encoding="utf-8")
    if homepage.count('script.src = "/assets/ok-ai-lite-preview.js";') != 1:
        raise SystemExit("Production homepage missing exactly one Lite loader")
    if 'script.src = "/assets/ok-ai-floating-demo.js";' in homepage:
        raise SystemExit("Production homepage contains old DEMO loader")
    for name, source in (("homepage", homepage), ("MkDocs AI", ai_page), ("Lite widget", widget)):
        for domain in ("preview.openkubes.org", "openkubes.org"):
            if domain not in source:
                raise SystemExit(f"{name}: approved website host missing: {domain}")
    if "ok-ai-lite-preview.js" not in ai_page:
        raise SystemExit("Production MkDocs AI page missing Lite loader")
    if "No AI backend" not in widget or "Beta 1.1 only answers" not in widget:
        raise SystemExit("Lite widget refusal and static backend disclosure missing")
    print("GitHub Pages production candidate safety checks passed")

if __name__ == "__main__":
    main()
