#!/usr/bin/env python3
"""Preserve published /docs source-file URLs in the generated preview site.

MkDocs renders selected Markdown as pretty URLs. Keep the original Markdown
files reachable under their old .md paths too, and preserve legacy standalone
HTML/JSON/scripts. Never change the source docs/ tree or overwrite generated
MkDocs pages. This is a compatibility layer, not a replacement for reviewing
site links and production cutover.
"""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs"
SITE = ROOT / ".mkdocs-site"
EXCLUDED = {"CNAME", "index.html"}

def main():
    if not SITE.is_dir() or not (SITE / "index.html").is_file():
        raise SystemExit("Run MkDocs, preserve-homepage, and render-navigation first")
    if not SOURCE.is_dir():
        raise SystemExit("Legacy docs/ source is missing")
    copied = reused = 0
    for source in sorted(SOURCE.rglob("*")):
        if source.is_symlink():
            raise SystemExit(f"Refusing symlink in published docs: {source}")
        if not source.is_file():
            continue
        relative = source.relative_to(SOURCE)
        if len(relative.parts) == 1 and relative.name in EXCLUDED:
            continue
        destination = SITE / relative
        if destination.exists():
            if not destination.is_file() or source.read_bytes() != destination.read_bytes():
                raise SystemExit(f"Legacy URL collision with different content: /{relative.as_posix()}")
            reused += 1
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied += 1
    print(f"Legacy URL preservation: {copied} files copied, {reused} identical assets already staged")

if __name__ == "__main__":
    main()
