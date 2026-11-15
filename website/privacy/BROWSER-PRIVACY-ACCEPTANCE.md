# OpenKubes browser privacy acceptance (manual evidence)

## Scope
Only `openkubes.org` and `preview.openkubes.org`. The audit runs in a clean Chromium context on the homepage and `/ai/`, then submits one predefined non-sensitive Ask OK AI Lite question on the homepage. No marketing acceptance, external links, or production publication is performed.

## How to run
After this workflow is merged and reviewed, manually select **Actions → OpenKubes browser privacy evidence (manual, no deployment) → Run workflow** on `main`. Retrieve artifact `openkubes-browser-privacy-audit`.

The test captures only hostnames, resource types, request counts, HTTP status, browser error types and **counts** of cookies/storage. It does **not** save cookie values, storage values or keys, user-entered content, complete URLs, request bodies, responses, HAR, or personal IP addresses.

A nonzero cookie or storage count is **not automatically proof of unlawful tracking**; review necessity, provenance and consent conditions separately. Passing the checker is **not** certification of privacy compliance.

## Review gates
- [ ] Both origins and both routes resolve and return non-error HTTP responses.
- [ ] No known ad/analytics/remote-font domains appear in requests.
- [ ] Ask OK AI Lite opens and submits a synthetic question with no additional remote third-party requests.
- [ ] Explain every third-party hostname that appears, even when absent from the denylist.
- [ ] For every cookie/storage count above zero, manually identify the initiator, purpose, storage duration and legal basis; do not publish secret values.
- [ ] Verify actual browser storage (including IndexedDB and service workers) manually in a clean browser profile. Automated counters intentionally do not inspect contents.
- [ ] Verify same results with DE/EN content/navigation and all published routes (not only these sampled pages).
- [ ] Independently verify live GitHub Pages deployment SHA/source, CDN, DNS and server access logs / retention.
- [ ] Complete and legally review the imprint and privacy notice drafts before a separate public legal-pages PR.

## Limitations
This is a **point-in-time sampled runtime audit**, not a full crawl or complete record of end-user data flows. DNS and outbound HTTP need to work on GitHub Actions runners. Network/access failures are reported rather than silently classified as success. Browser evidence does not establish processors, log retention or cross-border transfers.
