# OK-196 — Production cutover readiness

Status: **NOT APPROVED FOR CUTOVER**. This work prepares review only.

## Current hosting boundaries

- Existing public website: GitHub Pages sourced from `docs/` with `docs/CNAME` for `openkubes.org`.
- Unified website preview: Cloudflare Pages project `openkubes-preview`, built from `website-preview`, exposed at `preview.openkubes.org`.
- Do not change the live domain, CNAME, DNS, GitHub Pages settings or deployment source as part of this PR.

## Existing paths that must not disappear

The current build stages exactly five legacy articles and some homepage assets; it does **not** stage every published file from `docs/`. The inventory below is representative, not exhaustive:

- `/OpenKubes-Presentation.html`
- `/knowledge-graph-template.html`
- `/openkubes_knowledge_graph_force_layout.html`
- `/getting-started/`
- Many additional root-level Markdown files
- All images, downloads, SVG references and externally linked resources

Existing homepage, hero video, CTA destinations, legacy article permalinks, slash/trailing-slash behavior, case-sensitive file paths and search-engine indexed URLs must be checked before cutover.

## Production acceptance gates

1. Generate a complete path/asset inventory from existing published `docs/`, plus public internal links and known external inbound links.
2. Stage/copy or route all files appropriately; no loss of meaningful URLs, files or redirects.
3. Check source-of-truth references to `openkubes/openkubes`, `ok-local`, and `ok-cluster`, including images and relative links; the current upstream documentation import is only a smoke test.
4. Validate all navigation, articles, CTA links, local search, mobile layouts, the hero video, noindex policy for preview only, and SEO/sitemap for production.
5. Establish an independently reversible production deployment path and test rollback.
6. Approve the exact production change separately after visual and automated checks.

## Recommended release mechanics

**Decision:** Keep GitHub Pages serving `openkubes.org`; retain Cloudflare Pages for `preview.openkubes.org` only. Release the MkDocs output through a future approval-gated GitHub Actions Pages deployment, not via a DNS/hosting migration. Keep `website-preview` separate from reviewed `main` releases; preview `noindex` rules must never enter the production artifact. See `website/PRODUCTION-CUTOVER-RUNBOOK.md`.

## This PR

Only unifies the homepage **navigation brand** as text `OpenKubes` without disturbing the main homepage logo inside its hero section. The existing homepage source (`docs/index.html`) is unchanged.
