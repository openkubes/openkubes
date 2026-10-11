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
    print("GitHub Pages production candidate safety checks passed")

if __name__ == "__main__":
    main()
