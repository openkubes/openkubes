# Preview-first website publishing (OK-196)

Merge website changes into `main` through a reviewed PR. From a clean, current local `main` branch, with GitHub CLI (`gh`), `git`, and `curl` installed and GitHub access configured:

```bash
git switch main
git pull --ff-only origin main
make website-preview
# Visually review https://preview.openkubes.org/
make website-publish
```

`make website-preview` merges the current remote main into `website-preview`, commits the main SHA as `website/preview-main-sha.txt`, pushes the branch, and polls the Cloudflare-hosted marker `/.well-known/ok196-preview-main-sha.txt` until the expected revision is served. Returns to the original branch on success. Cloudflare must be connected to `website-preview` and publish the `.mkdocs-site` output of `website/scripts/cloudflare-build.sh`.

`make website-publish` checks that preview serves the same `main` SHA and that this commit is an ancestor of `website-preview`. It requires an interactive confirmation before temporarily enabling `OK196_PAGES_RELEASE_ENABLED`, dispatches `ok196-pages-release.yml` with `expected_sha`, watches the run and disables the variable on exit. The workflow rejects production builds if `main` advanced since review.

**Important:** Production remains on GitHub Pages; preview remains on Cloudflare Pages. No DNS changes. Do not merge or force-push during the publish window. The GitHub environment restrictions and the existing backup/rollback procedure remain in effect.

If deployment fails, investigate the GitHub Actions run or Cloudflare Pages deployment. If the release switch could not be disabled (e.g., an interrupted process), reset it manually:

```bash
gh variable set OK196_PAGES_RELEASE_ENABLED --repo openkubes/openkubes --body false
```

For a dry run (no deployment) use the GitHub Actions UI with `dry_run=true`. The old manual production form also now requires the full reviewed main SHA in `expected_sha`.
