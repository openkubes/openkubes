# Privacy by Design — OpenKubes Website Baseline Audit

Status: initial source audit, 2026-11-14. **No production changes.** This document is an audit record and implementation proposal, not a compliance certificate.

## Governance decisions
- **Kubernauts GmbH** is the legal website operator for openkubes.org.
- **Clouds Sky GmbH** remains an OpenKubes project supporter, not a co-operator by default.
- Remove marketing/analytics pixels and unnecessary tracking from openkubes.org and kubernauts.de.
- Prefer a cookie-banner-free website after verifying all storage, third-party and runtime behavior.
- **Ask OK AI Lite** remains a curated, browser-only preview without AI backend.

## Verified source observations (openkubes/openkubes default branch)
1. `docs/index.html`: YouTube thumbnail `https://i.ytimg.com/vi/_LJ8tCLHrO0/hqdefault.jpg` loads as an `img` before a visitor clicks the YouTube outbound link (around line 608). **P1: replace with locally served image/asset.**
2. `docs/index.html`: homepage footer currently describes Clouds Sky GmbH and Kubernauts GmbH jointly as developers/supporters (around line 806). **P1: add clear legal operator vs project supporter wording.**
3. `docs/index.html`: no verified dedicated privacy/imprint links in the inspected homepage markup. **P1: create and link operator-specific legal pages.**
4. `website/assets/ok-ai-lite-preview.js`: browser-only curated allowlisted responses, no `fetch`, `localStorage`, `sessionStorage`, cookie access, telemetry, or AI backend in inspected source. **Preserve this behavior and add regression tests.**
5. No Google Tag Manager, GA4, Google Ads or LinkedIn Pixel markers were found in the inspected `docs/index.html`. **This is not yet a full-site/network audit.**

## Companion site: kubernauts.de (public-page review only)
- Current published DE privacy notice still discusses GTM, GA4, Google Ads, LinkedIn Insight Tag, OpenAI Ads and consent storage `kubernauts-consent-v2`, as well as unresolved hosting/retention/vendor placeholders.
- The public home page currently exposes a consent dialog with statistics and marketing categories.
- Repository implementation and runtime requests have **not** been independently verified in this audit (repository connector access unavailable). **Do not claim tags are active solely from notice text.**

## Proposed PR sequence
1. **OK-PR1 — third-party default-load removal:** replace externally loaded YouTube thumbnail with first-party asset; audit every static page/template, fonts and all subresources; keep outbound links click-initiated.
2. **OK-PR2 — legal/operator:** add German and, if published, English legal information and privacy notices; name Kubernauts GmbH as operator; list Clouds Sky as supporter separately. Verify actual hosting, logs, deletion intervals, subprocessors before finalizing legal text.
3. **OK-PR3 — privacy regression guard:** automated grep/build tests for forbidden domains and tracking patterns; Lite assistant test that no requests or persistence are added.
4. **KN-PR1 — tracker removal:** remove GTM, GA4, Ads/LinkedIn/OpenAI measurement integrations (including conversion hooks, related state and dead code) across all DE/EN pages; keep intentional outbound Calendly as a link.
5. **KN-PR2 — consent and notices:** remove obsolete consent UI/storage only after runtime checks show no consent-requiring functionality remains; rewrite bilingual privacy notices to reflect actual data processing.
6. **Both — gated QA:** review preview builds in clean browser profiles with no consent/accepted consent, capture all network requests + cookies/localStorage/sessionStorage and server response headers; verify no tracking requests, broken links or accessibility regressions; peer review then human-controlled merge.

## Acceptance criteria (production gate)
- No automatic calls to `googletagmanager.com`, `google-analytics.com`, Google Ads conversion domains, `snap.licdn.com`, or marketing-pixel endpoints.
- No third-party thumbnails or remotely hosted fonts without a documented necessity and lawful configuration.
- No non-essential cookies/storage or silent tracking on first load, navigation, or CTA interactions.
- No consent banner unless the verified implementation genuinely needs it; do not remove consent controls prematurely.
- Each legal page has accurate operator, purposes, lawful bases, processors, retention and third-country disclosures; all placeholders resolved; legal review before release.
- Ask OK AI Lite remains self-contained with no browser-to-AI or analytics traffic.
- CI passes, independent reviewer approves, release plan includes rollback; **no direct production changes**.

## Remaining evidence to gather
- Full repository tree/actual deployment build and artifact inspection for both sites.
- Browser network HAR, cookie/storage screenshots, response headers, DNS/CDN/hosting/subprocessor inventory, logs retention.
- Audit of all routes and sibling subdomains only if included explicitly in this project's scope.
- Verify all claims against final deployed artifacts, not only source files.
