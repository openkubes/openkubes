# ADR-Platform-041 — Unified OpenKubes website and documentation build

- **Status:** Proposed (OK-196 spike; not approved for production)
- **Date:** 2026-10-11
- **Decision scope:** Publishing and documentation delivery, not platform runtime contracts
- **Tracking:** https://kubernauts.atlassian.net/browse/OK-196

## Context

The public website is currently published from the main repository's `docs/`
directory, including `index.html`, `CNAME`, media and Markdown pages.
Developer documentation additionally lives in the `ok-local` and `ok-cluster`
repositories. The publishing system should unify navigation, search and branding
without transferring content ownership or breaking public URLs.

## Proposed decision

Build one static website using MkDocs and one preview-tested publishing
pipeline, ultimately served at `https://openkubes.org/` with developer
documentation under `/docs/`.

1. Source Markdown remains in its owning Git repository.
2. The central build checks out pinned repository revisions and stages content
   without modifying upstream files.
3. The initial spike publishes **only CI artifacts**, with no Pages deployment,
   DNS, CNAME or production branch changes.
4. The existing homepage, video, CTAs, blog and URLs must survive migration.
5. Cross-repository links, asset paths and old URL mappings require explicit
   validation before production cutover.
6. Publishing and rollback require a separate reviewed change and approval.

## Alternatives

- Separate `docs.openkubes.org`: easier isolation, but duplicates navigation,
  domain experience and cross-site search.
- Git submodules: reproducible but awkward for editors and documentation
  build orchestration; prefer pinned CI checkouts.
- Copying all documentation into the website repo: rejected due to duplicate
  sources of truth.
- Replacing existing website immediately: rejected due to loss-of-content,
  visual and URL compatibility risk.

## Consequences and open questions

A separate staging tree and explicit source mapping are required. The
production homepage may need a custom Material override or a controlled
HTML integration, rather than a forced Markdown rewrite. We must inventory
legacy URLs, verify Markdown relative links and ensure a safe rollback.
The initial two-page integration is a smoke test, **not** proof that all
documentation is migrated.

## Acceptance gates

- CI `mkdocs build --strict` passes for pinned source revisions.
- Public docs can be rendered with consistent navigation/search.
- All migrated links, media, historical URLs and marketing features are checked.
- Cutover decision is explicit; no deployment is triggered by the spike PR.
