# Blog editorial dates (Phase 1)

This phase covers **all 12 articles listed in `website/scripts/stage-legacy.py:ARTICLES`**. Tutorials, Architecture pages and the homepage are explicitly out of scope.

Every staged blog article receives a visible, accessible line immediately after its H1:

```text
Published: YYYY-MM-DD · Last updated: YYYY-MM-DD
```

- **Published** is sourced from an explicit `published: YYYY-MM-DD` frontmatter field, otherwise the date of the **first available commit** affecting that article's source Markdown.
- **Last updated** is sourced from an explicit `updated: YYYY-MM-DD` frontmatter field, otherwise the date of the **latest commit** affecting that article's source Markdown.
- Git derives source history via `git log --follow --format=%cs -- docs/<file>.md`; no build-time clock is used. Dates are based on commit date (in its recorded timezone), not publication/deployment time.
- The Git fallback is **a provenance proxy, not proof of when the article first appeared publicly**. For imported, renamed, historical or independently published articles, editors should set explicit dates after verification. Git's latest commit can be an editorial or formatting-only change; add explicit `updated` when preserving the meaningful-update date matters.
- The build requires a **full Git history** (non-shallow checkout); if missing, it fails rather than fabricating dates. Both preview and production release workflows currently use `fetch-depth: 0`.
- Source Markdown is not modified to add rendered HTML. The staging step injects a single metadata paragraph into its copy. The two dates have native `<time datetime="...">` elements and use CSS scoped to `.ok-editorial-dates`.
- All dates are ISO 8601 calendar dates. An invalid date, missing H1, invalid date order, or duplicate generated marker makes the build fail.
- This change is **not an automatic scheduled editorial date update**. A content change or explicit metadata change is required for a new date; re-running the build with the same commit cannot change metadata.

## How to override an individual article

Add to the existing YAML frontmatter (or add frontmatter if the article has none):

```yaml
---
published: 2025-09-12
updated: 2026-11-23
---
```

These are editorial declarations, not `date_created` filesystem timestamps. Preserve any existing `title`, `description` or other fields.

## Verification

```bash
python -m unittest discover -s website/tests -p 'test_blog_editorial_dates.py'
bash website/scripts/build-github-pages.sh
```

The second command stages, builds and validates the site but does **not** deploy it. It needs the standard pinned documentation sources and Python dependencies. Verify the actual published dates for historical articles in editorial review before release.
