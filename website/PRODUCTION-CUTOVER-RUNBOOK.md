# OK-196 — Production cutover runbook (draft)

**State:** NOT READY / NO PRODUCTION DEPLOYMENT AUTHORIZED.

## Architecture and isolation

- Public site: `https://openkubes.org` currently served by the existing GitHub Pages publication from `docs/`.
- Preview site: `https://preview.openkubes.org` on the Cloudflare Pages project `openkubes-preview` from `website-preview`.
- Current CI/Cloudflare build is preview-only; it intentionally emits `X-Robots-Tag: noindex, nofollow` and `robots.txt` disallow. **Never deploy this artifact to the public domain.**
- No edits to live DNS, current GitHub Pages configuration or its `docs/CNAME` in this PR.

## Automated URL audit

After `restore-legacy-urls.py`, run:

```sh
python website/scripts/audit-url-compatibility.py
```

The machine-readable report `.mkdocs-site/url-compatibility-report.json` includes required public paths, missing raw source files, and possible Jekyll-rendered `.html` URLs that require a deployed-site comparison. A passing CI confirms only the checked paths and files, **not** full historical URL parity.

## Cutover gates (all required before approval)

- [ ] Inventory every existing `https://openkubes.org` URL, including Jekyll `.html`, `/getting-started/`, images, presentations, redirect behavior, and outbound/internal links. Crawl the currently live site and save the evidence.
- [ ] Diff current live HTTP status codes/redirect destinations against the candidate Cloudflare deployment. Resolve missing URLs with redirects or compatible output pages; preserve query/fragment behavior where practical.
- [ ] Verify the homepage hero video, sponsors, blog permalinks, generated navigation, documentation, on-site search, mobile layout, canonical/meta tags, sitemap and accessibility on the Cloudflare candidate.
- [ ] Document precisely which `ok-local` and `ok-cluster` documents are included; the current two-file staging is incomplete and must not be described as full documentation.
- [ ] Configure a **separate** Cloudflare Pages production project/build path or explicitly approve a preview-to-production migration. Production artifact must not contain blanket `noindex`, `Disallow: /`, or the GitHub Pages `CNAME` file.
- [ ] Validate the candidate on an alternate domain before touching `openkubes.org`; capture screenshots and smoke tests, check TLS, DNS and custom-domain verification on Cloudflare.
- [ ] Record Route 53 current DNS RRsets and TTLs and current GitHub Pages publishing settings; identify authorized operator, rollback owner and maintenance window.
- [ ] Approve the final build commit and record an explicit go/no-go decision.

## Suggested rollout

1. Freeze and record the current GitHub Pages publication plus Route 53 DNS values (rollback snapshot).
2. Build the approved production artifact from a pinned reviewed `main` commit with a production-specific configuration (not the preview script).
3. Verify the new site before DNS change and check domain binding/TLS status with Cloudflare Pages.
4. Cut over `openkubes.org` and, if applicable, `www` using the approved Route 53 record change.
5. Confirm all critical URLs, redirects, robots/sitemap, and media at the public domain from at least two independent clients; monitor HTTP errors.
6. On failure, restore prior Route 53 records and GitHub Pages custom-domain setup, acknowledging DNS cache/TTL delays; validate original live site after rollback.

**Rollback isn't instantaneous:** DNS caching, certificate provisioning and Cloudflare/GitHub Pages custom-domain verification can delay restoration. Prepare the exact operational steps with the real current DNS configuration before switching.
