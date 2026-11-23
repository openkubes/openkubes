#!/usr/bin/env python3
"""Assert the MkDocs candidate can be hosted on the existing GitHub Pages domain."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / ".mkdocs-site"

def check_unapproved_legal_drafts(site: Path) -> None:
    """Block accidental release of the *internal* legal-review draft files.

    This is intentionally narrow: publication of finalized legal notices still
    requires a separate reviewed change and an actual browser/network audit.
    """
    draft_names = {
        "LEGAL-NOTICE-DRAFT-DE.md",
        "PRIVACY-NOTICE-DRAFT-DE.md",
        "LEGAL-REVIEW-EVIDENCE-2026-11-15.md",
    }
    for path in site.rglob("*"):
        if not path.is_file():
            continue
        if path.name in draft_names:
            raise SystemExit(f"Unapproved legal review source shipped: {path}")
        if path.suffix.lower() != ".html":
            continue
        html = path.read_text(encoding="utf-8", errors="replace")
        if "Entwurf: Impressum für openkubes.org (nicht veröffentlicht)" in html:
            raise SystemExit(f"Unapproved imprint draft rendered: {path}")
        if "Entwurf: Datenschutzerklärung für openkubes.org (nicht veröffentlicht)" in html:
            raise SystemExit(f"Unapproved privacy draft rendered: {path}")


def main():
    from retired_widgets import check_retired_widgets

    if (SITE / "CNAME").read_text(encoding="utf-8").strip() != "openkubes.org":
        raise SystemExit("GitHub Pages production CNAME is missing or incorrect")
    if not (SITE / ".nojekyll").is_file():
        raise SystemExit("GitHub Pages .nojekyll marker is missing")
    robots = (SITE / "robots.txt").read_text(encoding="utf-8")
    if "Disallow: /" in robots or "Allow: /" not in robots:
        raise SystemExit("Production must be publicly indexable")
    if (SITE / "_headers").exists():
        raise SystemExit("Legacy preview _headers must not be shipped")
    check_unapproved_legal_drafts(SITE)
    for name in ("index.html", "getting-started/index.html",
                 "agentic-operations-reference-architecture/index.html",
                 "agentic-operations-reference-architecture.html",
                 "OpenKubes-Presentation.html", "search/search_index.json"):
        if not (SITE / name).is_file():
            raise SystemExit("Missing production candidate path: " + name)
    # Lightweight release guard: published notices and both footer contexts exist.
    for relative in ("legal/imprint/index.html", "legal/privacy/index.html"):
        page = SITE / relative
        if not page.is_file():
            raise SystemExit("Missing public legal page: " + relative)
        rendered = page.read_text(encoding="utf-8")
        for expected in ("Kubernauts GmbH", "contact@kubernauts.de"):
            if expected not in rendered:
                raise SystemExit(f"{relative}: required operator detail missing: {expected}")
    homepage_legal = (SITE / "index.html").read_text(encoding="utf-8")
    ai_legal = (SITE / "ai/index.html").read_text(encoding="utf-8")
    for name, html in (("homepage", homepage_legal), ("AI page", ai_legal)):
        for href in ("/legal/imprint/", "/legal/privacy/"):
            if f'href="{href}"' not in html:
                raise SystemExit(f"{name}: legal footer link missing: {href}")
    check_retired_widgets(SITE)
    print("GitHub Pages production candidate safety checks passed")

if __name__ == "__main__":
    main()
