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
    guide = pages / "community" / "how-to-update-docs.md"
    if not guide.is_file():
        raise SystemExit(f"Missing community contribution guide: {guide}")
    shutil.copy2(guide, TARGET / "community" / "how-to-update-docs.md")
    # Stage the dedicated OK AI capability pages from source-owned Markdown.
    ai_source = pages / "ai"
    ai_target = TARGET / "ai"
    ai_target.mkdir(parents=True, exist_ok=True)
    for filename in ("index.md", "chat-preview.md", "open-webui.md", "openclaw.md", "kagent-platform-diagnostics.md", "agentic-operations.md", "ai-glossary-newbies.md", "ai-roadmap.md"):
        source_page = ai_source / filename
        if not source_page.is_file():
            raise SystemExit(f"Missing OK AI page: {source_page}")
        shutil.copy2(source_page, ai_target / filename)
    # Stage the source-owned OK Observability capability pages.
    observability_source = pages / "observability"
    observability_target = TARGET / "observability"
    observability_target.mkdir(parents=True, exist_ok=True)
    for filename in ("index.md", "stack.md", "contract.md", "installation.md"):
        source_page = observability_source / filename
        if not source_page.is_file():
            raise SystemExit(f"Missing OK Observability page: {source_page}")
        shutil.copy2(source_page, observability_target / filename)
    # Stage the source-owned Developer Workspace capability pages.
    workspace_source = pages / "developer-workspace"
    workspace_target = TARGET / "developer-workspace"
    workspace_target.mkdir(parents=True, exist_ok=True)
    for filename in ("index.md", "architecture.md", "coding-agents.md", "status.md"):
        source_page = workspace_source / filename
        if not source_page.is_file():
            raise SystemExit(f"Missing Developer Workspace page: {source_page}")
        shutil.copy2(source_page, workspace_target / filename)
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
    # Preview-only floating OK AI UI demo assets. The hostname guard in
    # website/overrides/main.html prevents loading them on production.
    for name in ("ok-ai-floating-demo.js", "ok-ai-floating-demo.css"):
        source = ROOT / "website" / "assets" / name
        if not source.is_file():
            raise SystemExit(f"Missing floating UI asset: {source}")
        shutil.copy2(source, TARGET / "assets" / name)
    media = SOURCE / "media"
    if not media.is_dir():
        raise SystemExit("Legacy media directory not found.")
    shutil.copytree(media, TARGET / "media", dirs_exist_ok=True)
    print(f"Staged {len(ARTICLES)} existing permalink articles and homepage assets.")

if __name__ == "__main__":
    main()
