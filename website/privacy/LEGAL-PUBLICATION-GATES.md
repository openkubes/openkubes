# OpenKubes legal-page publication gates

**Status: NOT APPROVED FOR PUBLICATION.** This is a single handoff checklist for moving the existing internal DE/EN drafts into public legal pages. It deliberately distinguishes confirmed project facts from details requiring evidence.

## Existing documents

- `LEGAL-NOTICE-DRAFT-DE.md` and `LEGAL-NOTICE-DRAFT-EN.md`
- `PRIVACY-NOTICE-DRAFT-DE.md` and `PRIVACY-NOTICE-DRAFT-EN.md`
- `PREVIEW-PRIVACY-ACCEPTANCE-2026-11-15.md` and `LEGAL-REVIEW-EVIDENCE-2026-11-15.md`

## Verified within project / public-source level

- Legal website operator: **Kubernauts GmbH**; Clouds Sky GmbH is project supporter.
- Contact as published by Kubernauts: Im Mediapark 4C, 50670 Köln, contact@kubernauts.de, +49 221 379 90 680.
- Run #3 Preview Chromium sample: only `preview.openkubes.org` requested, 0 observed cookies and local/session-storage entries on `/` and `/ai/`; Lite question caused no extra requests.
- Production site is deployed through GitHub Pages; the Preview environment uses Cloudflare Pages (project publishing configuration and reviewed Pages settings).
- Commercial-register aggregator reports Amtsgericht Köln, HRB 94032. **Treat as provisional pending official extract**.

## Required factual evidence before legal sign-off

| Item | Needed evidence | Owner |
| --- | --- | --- |
| Authorized representative and exact full name | Current official German commercial-register extract | Kubernauts management |
| Registry number / company seat | Current official extract, not third-party aggregator | Kubernauts management |
| VAT ID (if assigned) | Company accounting/official record | Kubernauts finance |
| Editorial responsibility | Determination of §18(2) MStV applicability, then details if applicable | Legal reviewer |
| DPO or privacy contact | Confirm actual appointment and reachable contact; director != automatic DPO | Kubernauts management |
| Production/preview hosting data flows | GitHub and Cloudflare actual processing terms and architecture, DNS/proxy validation | Website operator |
| Server and email logs | Verified categories, provider-specific retention/criteria, access and recipients | Website operator / mail admin |
| Third-country transfers | Actual recipients and safeguards/agreements | Legal/privacy reviewer |
| Entire site runtime | Production network/terminal-storage tests and representative full-site route review | Website engineering |

## Publication implementation (separate approved PR)

1. Put **final** German and English documents in public, stable routes, e.g. `/legal/imprint/`, `/legal/privacy/` (language selector or localized URLs as reviewed); do not build from the internal draft files.
2. Link both directly from the **legacy homepage footer** in `docs/index.html` and the **MkDocs theme footer** via `website/overrides/main.html` or a reviewed Material-theme footer override. Ensure links survive the staging/preservation scripts.
3. Test both URLs, broken links, accessibility, mobile layout, consistent operator information, SEO/indexability and legal correctness.
4. Update tests to require the public legal pages and links only when those approved pages genuinely exist; do not weaken the existing unpublished-drafts guard.
5. Run the regular non-deploying build and preview browser audit before the explicit production release.
6. Obtain legal approval and an explicit publication decision separately from any technical privacy release.

**No code in this handoff activates or publishes legal pages.**
