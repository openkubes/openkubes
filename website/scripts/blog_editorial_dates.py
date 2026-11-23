#!/usr/bin/env python3
"""Add editorial dates to the staged blog articles (never mutate source Markdown).

Frontmatter may explicitly supply published: YYYY-MM-DD and updated: YYYY-MM-DD.
Otherwise derive both from the source file's Git history, not the build clock.
A full, non-shallow Git checkout is required to avoid inventing publication dates.
"""
from __future__ import annotations

from datetime import date
from html import escape
from pathlib import Path
import re
import subprocess


DATE_LINE = re.compile(r"^(published|updated):\s*['\"]?(\d{4}-\d{2}-\d{2})['\"]?\s*$", re.M)
HEADING = re.compile(r"(?m)^# .+$")


def overrides(markdown: str) -> dict[str, str]:
    if not markdown.startswith("---\n"):
        return {}
    end = markdown.find("\n---\n", 4)
    if end < 0:
        raise ValueError("Unterminated YAML frontmatter")
    return dict(DATE_LINE.findall(markdown[4:end]))


def checked_date(value: str) -> str:
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError(f"Noncanonical date: {value}")
    return value


def git_dates(repository: Path, relative_file: Path) -> tuple[str, str]:
    def git(*args: str) -> str:
        proc = subprocess.run(
            ["git", *args], cwd=repository, capture_output=True,
            text=True, check=True,
        )
        return proc.stdout.strip()

    if git("rev-parse", "--is-shallow-repository") != "false":
        raise RuntimeError("Blog dates require a full Git checkout (fetch-depth: 0)")
    commits = git("log", "--follow", "--format=%cs", "--", relative_file.as_posix()).splitlines()
    if not commits:
        raise RuntimeError(f"No Git history for blog article: {relative_file}")
    return checked_date(commits[-1]), checked_date(commits[0])


def add_editorial_dates(markdown: str, published: str, updated: str) -> str:
    published, updated = checked_date(published), checked_date(updated)
    if updated < published:
        raise ValueError("Updated date must not precede published date")
    if 'class="ok-editorial-dates"' in markdown:
        raise ValueError("Editorial dates already injected")
    heading = HEADING.search(markdown)
    if heading is None:
        raise ValueError("Blog article missing H1 heading")
    note = (
        '\n\n<p class="ok-editorial-dates">'
        f'<span>Published: <time datetime="{escape(published)}">{escape(published)}</time></span>'
        ' <span class="ok-editorial-dates__separator" aria-hidden="true">·</span> '
        f'<span>Last updated: <time datetime="{escape(updated)}">{escape(updated)}</time></span>'
        '</p>'
    )
    return markdown[:heading.end()] + note + markdown[heading.end():]


def stage_article(source: Path, destination: Path, repository: Path) -> None:
    relative = source.relative_to(repository)
    markdown = source.read_text(encoding="utf-8")
    explicit = overrides(markdown)
    first, last = git_dates(repository, relative)
    published = explicit.get("published", first)
    updated = explicit.get("updated", last)
    destination.write_text(add_editorial_dates(markdown, published, updated), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit("Use stage-legacy.py, which applies this only to the blog ARTICLES.")
