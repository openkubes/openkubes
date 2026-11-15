# OpenKubes legal and technical evidence register — 2026-11-15

**Status:** Internal review only. Companion to PR #492. No public legal page, deployment or production DNS change is authorized by this record.

## Evidence matrix

| Subject | Evidence | Status / required action |
| --- | --- | --- |
| Operator | Project decision: Kubernauts GmbH operates openkubes.org. `docs/index.html` identifies Kubernauts as website operator after PR #491. | Confirm legal accountable entity in final imprint. |
| Project supporter | Project decision and homepage: Clouds Sky GmbH is project supporter. | Keep outside operator/data-controller wording unless independently documented. |
| Company address | Existing Kubernauts legal/contact pages reference Im Mediapark 4C, 50670 Köln. | Verify against official company records before public release. |
| Company registration | Commercial-register aggregators list Amtsgericht Köln, HRB 94032. | **Not an official extract.** Verify current HRB, registered seat, representation, exact name spelling and tax number with primary records. |
| Production website hosting | `website/PUBLISH-FLOW.md` and `website/PRODUCTION-READINESS.md`: GitHub Pages for openkubes.org. `.github/workflows/ok196-pages-release.yml` implements manually gated GitHub Pages publication. | Document GitHub's actual roles, data flow, IP/server access logs, processing agreements and retention policies. Confirm current live endpoint independently. |
| Preview website hosting | `website/PUBLISH-FLOW.md`, `website/PRODUCTION-READINESS.md`: Cloudflare Pages preview.openkubes.org. | Determine whether separate privacy disclosure for preview access is required; verify Cloudflare logs, access controls, storage and subprocessors. |
| DNS / traffic proxy | Production readiness file describes Route 53 DNS at that design point. | **May be stale.** Verify live authoritative DNS and actual proxy/CDN path; do not infer current infrastructure from a historical runbook. |
| MkDocs external fonts | PR #493 added `theme.font: false` on `main`. The 2026-11-15 runtime audit still observed `fonts.googleapis.com` and `fonts.gstatic.com` on both `/ai/` deployments. | **Release drift suspected, not yet proven.** Verify deployed GitHub Pages source and Cloudflare preview SHA against the reviewed build; do not remove the source fix. |
| Homepage video | PR #490 replaces YouTube thumbnail URL with CSS-local preview and click-through link. | Verify published output and all other video/embed routes. |
| Ask OK AI Lite | `website/assets/ok-ai-lite-preview.js` has curated local replies and no `fetch`/Storage APIs in inspected source. | Verify final built JS and browser interaction traffic. |
| Analytics / consent | No tracking tags found in inspected homepage; no proof of whole-site absence. | Full-page crawl + clean-profile HAR + cookie and all client storage inventory. |
| Contact e-mail | Website routes visitors to Kubernauts contact channels; notice draft lists contact@kubernauts.de. | Verify actual responsible inbox, processor(s), retention, legal bases and data subject rights channel. |

## Release constraints

1. PR #492 contains **non-public drafts under `website/privacy/`**. Do not add them to `mkdocs.yml`, `docs/` or website navigation until every published assertion has evidence.
2. Final legal copy must cover GDPR Article 13 transparency, legitimate-interest balancing where used, § 25 TDDDG for terminal access, DDG § 5 operator duties, and any applicable MStV requirements after specialist legal review.
3. Record primary-source confirmation for commercial-register and VAT data, GDPR role allocations and service-provider disclosures; don't convert review placeholders to invented values.
4. Build and network audit must include production and preview, homepage and docs route, external links vs auto-loaded resources, requests before consent, browser persistence, response headers and embedded scripts.
5. Only after evidence and legal sign-off open a **separate public legal-pages PR**; make sure both Markdown theme pages and preserved legacy homepage have visible legal links.

## Runtime browser evidence — 2026-11-15 (workflow #2)

**Source:** Manual GitHub Actions workflow `website-browser-privacy-audit.yml`, run [43727432247](https://github.com/openkubes/openkubes/actions/runs/43727432247), produced the sanitized evidence artifact `openkubes-browser-privacy-audit`. The workflow exited with status 1 because it detected prohibited third-party hosts. This is a **successful detection of a privacy issue**, not a tool-installation failure.

Observed from the runner logs:

| Visited origin | Route | Third-party automatic hosts |
| --- | --- | --- |
| `https://openkubes.org` | `/` | `i.ytimg.com` |
| `https://openkubes.org` | `/ai/` | `fonts.googleapis.com`, `fonts.gstatic.com` |
| `https://preview.openkubes.org` | `/` | `i.ytimg.com` |
| `https://preview.openkubes.org` | `/ai/` | `fonts.googleapis.com`, `fonts.gstatic.com` |

**Source vs runtime comparison:** `docs/index.html` on `main` no longer references `i.ytimg.com` (PR #490). `mkdocs.yml` contains `font: false` (PR #493). Both live hosts nevertheless requested the blocked hosts, so stale/deviating deployed artifacts or an alternative build/source are **likely**. The precise release cause remains unverified.

### Release/order of operations

1. **Do not re-implement the same source changes.** Preserve PR #490 and #493 and confirm their generated output is free of the blocked resources.
2. **Inspect production GitHub Pages Settings → Pages:** confirm deployment source (branch `main:/docs` vs GitHub Actions), recent deployment SHA, custom domain, and the served HTML. A merged PR does not necessarily trigger a Pages artifact release.
3. **Inspect the Cloudflare Preview revision** by comparing `https://preview.openkubes.org/.well-known/ok196-preview-main-sha.txt` to `origin/main`; this is the documented preview parity mechanism.
4. **Preview-only synchronization first:** use the existing `make website-preview` workflow only after validating current source/permissions. This updates the **preview** branch/deployment and must not be confused with a production release.
5. **Rerun the browser audit on refreshed preview** and compare sources and third-party hosts. Expected: no YouTube thumbnail requests on `/` or Google Fonts requests on `/ai/`.
6. **Production is a separate release gate.** Do not change Pages deployment source, publish candidate, flip release variables, or deploy to `openkubes.org` without an explicit operator release decision. Follow `website/PUBLISH-FLOW.md` and `website/PRODUCTION-CUTOVER-RUNBOOK.md`, including rollback plan and URL/SEO checks.
7. **Legal disclosures still blocked:** finish official registry/representative/VAT verification, actual hosting/log processors and retention, and legal review; the internal draft pages must not be published.
8. **Scope of audit:** only four sampled routes. Confirm the wider route set and storage evidence before declaring privacy compliance.

**Interpretation:** The failed audit is useful evidence of residual browser requests. It cannot by itself prove the current hosting revision, data retention, cookie compliance, or the absence of other trackers.
