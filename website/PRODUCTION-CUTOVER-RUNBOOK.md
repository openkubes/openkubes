# OK-196 — GitHub Pages MkDocs release runbook (draft)

**Status: NOT APPROVED FOR PUBLICATION.** This plan changes only the build, not the existing hosting provider or Git branches.

## Agreed architecture

- GitHub `main` remains the source of truth.
- **GitHub Pages continues to serve `https://openkubes.org`** with the existing custom domain and Route 53 DNS.
- Cloudflare Pages continues to serve **preview only** at `https://preview.openkubes.org`.
- Currently GitHub Pages publishes the `docs/` directory. The MkDocs production candidate is built separately into `.mkdocs-site/`.
- This PR DOES NOT update GitHub Pages publishing settings, DNS, custom domains, or `docs/index.html`.

## CI production candidate (no deploy)

The PR workflow now produces two independent artifacts:

1. **Preview output** from the current MkDocs preview pipeline.
2. **GitHub Pages candidate** produced with `bash website/scripts/build-github-pages.sh`.

The production candidate has:
- The preserved `openkubes.org` CNAME.
- `.nojekyll` so GitHub Pages will serve the pre-rendered MkDocs HTML rather than try to process Markdown with Jekyll.
- `robots.txt` allowing indexing, with no Cloudflare preview-only `_headers`.
- Legacy source assets, legacy `.html` pages, the original homepage plus unified navigation, MkDocs subpages and local search.
- Automated checks from `check-github-pages-build.py`.

**A generated artifact is not a production deployment.** The separate publishing workflow is intentionally not created or activated here.

## Legacy URLs and comparison

The prior live-versus-preview HTTP test covered 63 URLs and identified 21 historical Markdown-derived `.html` URLs serving 200 on GitHub Pages but 404 on an older Cloudflare deployment.

`render-legacy-html.py` now generates these paths in the preview and production candidate builds. The later deployed candidate `c35fbbec.openkubes-preview.pages.dev` passed a **63-URL** live HTTP check with **0 regressions and 0 network failures** in GitHub Actions run `38179342639`. This does not prove full content or redirect parity.

The manually dispatchable URL comparison is available after the workflow changes are on the default branch. It produces JSON evidence and fails if currently reachable URLs turn into HTTP errors on the candidate. The full inventory of historical redirects, navigation and search must still be reviewed.

## Publication gates

- [ ] Production candidate GitHub Action succeeds, and its artifact contains `CNAME`, `.nojekyll`, valid `robots.txt` and complete site files.
- [ ] Fresh Cloudflare preview is visually reviewed and live HTTP comparison succeeds or every intentional redirect is documented.
- [ ] Verify site navigation, blog, historical `.html` URLs, hero video, sponsors, Getting Started, downloadable assets, local search, mobile screens and canonical SEO tags.
- [ ] Confirm that imported `ok-local` and `ok-cluster` documentation is accurately described; currently only a small smoke-test selection is incorporated.
- [ ] Choose and test a **GitHub Actions deployment workflow** using GitHub's official Pages upload/deploy actions. Keep build and deploy separate, protected by environment permissions and an explicit go/no-go approval.
- [ ] Record the currently configured GitHub Pages source, custom domain and last-known-good site files. Confirm GitHub Pages can serve the new artifact as intended.
- [ ] Approve the exact production commit and release/rollback procedure.

## PR #352 manual release workflow (disabled by default)

The checked-in `.github/workflows/ok196-pages-release.yml` is **manual-only**:
no `push`, `pull_request`, or schedule events. Run it from the `main` branch
via **Actions -> OK-196 GitHub Pages MkDocs release (manual only) -> Run workflow**.
The default `dry_run: true` builds a downloadable production candidate and
does not publish.

For a release, all of the following are required:

1. The repository owner reviews the exact `main` commit and accepts the URL
   parity and browser checks. Record the SHA and release approval.
2. The owner creates or verifies the **`github-pages` GitHub Actions
   environment**, with **required reviewers**, before making a live release.
   GitHub plan and repository visibility can limit environment protection
   availability; verify the actual settings.
3. The owner configures repository Actions variable
   `OK196_PAGES_RELEASE_ENABLED=true` only during the approved maintenance
   window. The variable is absent by default; without it the deployment job is
   skipped. Disable it after completion.
4. Manually dispatch from `main` with `dry_run=false` and confirmation
   `PUBLISH_OPENKUBES_ORG`. The `github-pages` environment must then be
   approved by a reviewer.
5. **Before the first publication**, change the repository's GitHub Pages
   build/deployment source from "Deploy from a branch" to "GitHub Actions".
   This is an explicit, manual repository setting; **merging the workflow
   does not make this change**.

The build job uses pinned upstream docs, runs the strict MkDocs checks, and
preserves the rendered candidate as a workflow artifact. The publish job
downloads that **same artifact**; no second build occurs after approval.
Publishing uses `actions/configure-pages@v5`,
`actions/upload-pages-artifact@v3`, and `actions/deploy-pages@v4`.

**Security:** Do not enable the release variable or switch Pages source
until rollback preparation and review are complete. Dry runs do not have
Pages deployment permissions. If a workflow run fails after source switching,
existing production availability must be verified immediately.

## Controlled GitHub Pages switch (separate operational approval)


1. Keep the live `docs/` publication in place while testing MkDocs.
2. Configure GitHub Pages to use a protected **GitHub Actions** deployment source only after the publication workflow is approved. A `main` push must not automatically release without the agreed gate.
3. Build from a reviewed `main` commit and deploy the validated `github-pages` artifact using official Pages actions. Keep `openkubes.org` and DNS unchanged.
4. Run live URL, indexing, media and navigation smoke tests.
5. If necessary, redeploy the previously saved working site artifact via GitHub Actions. Changing the deployment source is operationally sensitive: confirm a rollback path beforehand.

No Cloudflare production domain, Route 53 changes, DNS cutover or GitHub Pages shutdown are part of this migration.
