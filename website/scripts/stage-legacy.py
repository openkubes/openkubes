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
    pages = ROOT / "website" / "pages"
    for section in ("features", "architecture", "blog", "community"):
        source_page = pages / section / "index.md"
        if not source_page.is_file():
            raise SystemExit(f"Missing standalone page: {source_page}")
        destination = TARGET / section
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_page, destination / "index.md")
    # Preserve the historical getting-started entry point as a rendered page.
    # Relative repository links in its source README point outside docs/.
    getting_started = SOURCE / "getting-started" / "README.md"
    if not getting_started.is_file():
        raise SystemExit("Legacy getting-started README missing")
    page = getting_started.read_text(encoding="utf-8")
    page = page.replace("](../../", "](https://github.com/openkubes/openkubes/blob/main/")
    entrypoint = TARGET / "getting-started"
    entrypoint.mkdir(parents=True, exist_ok=True)
    (entrypoint / "index.md").write_text(page, encoding="utf-8")
    for source in SOURCE.glob("*.svg"):
        shutil.copy2(source, TARGET / source.name)
    logo = SOURCE / "openkubes-logo.png"
    if not logo.is_file():
        raise SystemExit("Legacy logo is missing.")
    shutil.copy2(logo, TARGET / logo.name)
    shared_css = ROOT / "website" / "assets" / "openkubes-navigation.css"
    if not shared_css.is_file():
        raise SystemExit("Shared navigation CSS missing")
    (TARGET / "assets").mkdir(exist_ok=True)
    shutil.copy2(shared_css, TARGET / "assets" / shared_css.name)
    theme_css = ROOT / "website" / "assets" / "openkubes-theme.css"
    if not theme_css.is_file():
        raise SystemExit("Shared theme CSS missing")
    shutil.copy2(theme_css, TARGET / "assets" / theme_css.name)
    media = SOURCE / "media"
    if not media.is_dir():
        raise SystemExit("Legacy media directory not found.")
    shutil.copytree(media, TARGET / "media", dirs_exist_ok=True)
    print(f"Staged {len(ARTICLES)} existing permalink articles and homepage assets.")

if __name__ == "__main__":
    main()
