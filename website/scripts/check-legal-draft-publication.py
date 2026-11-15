#!/usr/bin/env python3
"""Prevent internal, unresolved legal drafts from shipping in a public website artifact.

This check intentionally does not certify legal completeness. It only enforces
that known review drafts and their explicit non-public notices stay internal.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SITE = ROOT / ".mkdocs-site"

DRAFT_FILENAME_MARKERS = (
    "legal-notice-draft",
    "privacy-notice-draft",
    "legal-review-evidence",
    "privacy-by-design-audit",
)
DRAFT_CONTENT_MARKERS = (
    "REVIEW REQUIRED. Dieser Entwurf",
    "REVIEW REQUIRED. Technischer",
    "nicht als fertige Datenschutzerklärung veröffentlichen",
    "nicht veröffentlicht)",
    "NOT READY TO PUBLISH",
)


def inspect(site: Path) -> list[str]:
    if not site.is_dir():
        return [f"Built website directory does not exist: {site}"]
    files = sorted(p for p in site.rglob("*") if p.is_file())
    if not files:
        return [f"Built website directory is empty: {site}"]
    failures = []
    for file in files:
        relative = file.relative_to(site).as_posix()
        if any(marker in relative.lower() for marker in DRAFT_FILENAME_MARKERS):
            failures.append(f"Non-public legal working file shipped: {relative}")
        if file.suffix.lower() in {".html", ".md", ".json", ".txt", ".xml"}:
            content = file.read_text(encoding="utf-8", errors="replace")
            for marker in DRAFT_CONTENT_MARKERS:
                if marker.casefold() in content.casefold():
                    failures.append(f"Unapproved legal draft content in {relative}: {marker}")
    return failures


def main() -> int:
    site = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SITE
    failures = inspect(site)
    if failures:
        for failure in failures:
            print("LEGAL RELEASE BLOCK:", failure, file=sys.stderr)
        return 1
    print("Legal draft publication guard passed (legal sign-off still required)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
