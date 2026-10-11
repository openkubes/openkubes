#!/usr/bin/env python3
"""Stage selected existing public articles and media without editing source docs."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs"
TARGET = ROOT / ".mkdocs-staging"
ARTICLES = (
    "agentic-operations-reference-architecture.md",
    "vault-secret-contract-blog-post.md",
    "the-contract-is-the-guardrail-blog-post.md",
    "openkubes-self-healing-blog-post.md",
    "openkubes-blog-post.md",
)
def main():
    if not (TARGET / "index.md").exists():
        raise SystemExit("Run build-docs.py first.")
    for name in ARTICLES:
        if not (SOURCE / name).is_file():
            raise SystemExit(f"Missing legacy article: {name}")
        shutil.copy2(SOURCE / name, TARGET / name)
    for source in SOURCE.glob("*.svg"):
        shutil.copy2(source, TARGET / source.name)
    media = SOURCE / "media"
    if not media.is_dir():
        raise SystemExit("Legacy media directory not found.")
    shutil.copytree(media, TARGET / "media", dirs_exist_ok=True)
    print(f"Staged {len(ARTICLES)} existing permalink articles and homepage media.")

if __name__ == "__main__":
    main()
