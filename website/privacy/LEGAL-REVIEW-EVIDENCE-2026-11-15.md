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
| MkDocs external fonts | `mkdocs.yml` uses Material theme without an explicit privacy/offline font setting. `website/overrides/main.html` does not show a font override. | **Open technical risk, not a proven request.** Examine generated HTML/CSS and browser HAR for `fonts.googleapis.com`, `fonts.gstatic.com`; if present, use bundled/local fonts or Material's supported disabling of remote fonts. |
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
