# OpenKubes Preview — Browser Privacy Acceptance Record

**Audit:** 2026-11-15T15:51:08.981Z (2026-11-15 16:51 MEZ)  
**Source:** manually dispatched GitHub Actions browser privacy audit, `target=preview`, run #3; reviewer-supplied sanitized artifact `openkubes-browser-privacy-audit.json`  
**Scope:** `https://preview.openkubes.org/`, `https://preview.openkubes.org/ai/`  
**Decision:** **PASS for the two sampled Preview routes against the automated criteria**. Not a GDPR compliance certification or authorization to deploy to production.

## Captured evidence

| Metric | Homepage / | OK AI /ai/ |
| --- | ---: | ---: |
| HTTP status | 200 | 200 |
| Total requests | 14 | 12 |
| Request hosts | preview.openkubes.org only | preview.openkubes.org only |
| Forbidden hosts | 0 | 0 |
| Document requests | 1 | 1 |
| Stylesheet requests | 4 | 6 |
| Script requests | 3 | 4 |
| Image requests | 5 | 0 |
| Media requests | 1 | 0 |
| XHR requests | 0 | 1 |
| document.cookie count before/after | 0 / 0 | 0 / 0 |
| Context cookie count before/after | 0 / 0 | 0 / 0 |
| localStorage entries before/after | 0 / 0 | 0 / 0 |
| sessionStorage entries before/after | 0 / 0 | 0 / 0 |
| Service-worker count before/after | 0 / 0 | 0 / 0 |
| JavaScript page errors | 0 | 0 |

**Ask OK AI Lite:** homepage widget found and tested using a predetermined synthetic question. Additional requests during interaction: **0**. Remote hosts during interaction: **none**. The /ai/ route did not have this interaction test (recorded `null`).

## Interpretation

- The earlier Preview requests to `i.ytimg.com`, `fonts.googleapis.com`, and `fonts.gstatic.com` are **not reproduced** by this fresh automated Preview audit.
- No third-party hosts were contacted on the two sampled routes during the audit.
- The one XHR request on `/ai/` was first-party (only preview.openkubes.org appears in the request hosts).
- No cookies or local/session storage entries were observed before/after navigation or the Lite interaction.
- **IndexedDB presence was not audited:** the collector records only that the API is supported, not whether any database was created.
- **Service workers were blocked** by the Playwright context. Counts of 0 do not establish their general absence.
- The audit is limited to two routes, one browser and a point in time; it does not verify every route, every browser, hosting logs, processors, retention policies, international transfers, or the legal necessity of consent for all conceivable features.

## Release and legal gates

- [x] Current Preview sample passes automated third-party host / basic storage / Lite-interaction guards
- [ ] Verify Preview-to-main SHA equality again immediately before release
- [ ] Document production GitHub Pages deployment source, current SHA and rollback
- [ ] Validate production candidate build, URL parity, SEO, visual/accessibility review, and broader-route network audit
- [ ] Obtain **explicit operator approval** before any production publish or Pages source switch
- [ ] After publishing, audit production separately and compare with approved Preview
- [ ] Verify formal operator/representative/registration/VAT facts against primary sources
- [ ] Verify hosting/DNS/CDN/mail processors, logs and retention; review legal bases
- [ ] Complete and legally review final DE/EN imprint and privacy notices; publish through a separate approved PR

**No production deployment and no public legal-notice publication is authorized by this record.**
