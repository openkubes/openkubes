# GitHub-only website publishing (OK-196)

The source of truth is reviewed `origin/main`. GitHub Actions builds downloadable previews and GitHub Pages serves production.

Historical records describe the former Cloudflare Pages preview at `preview.openkubes.org`. Any external project or DNS retirement is handled separately from the repository's publishing workflow.

## Build and inspect the preview

```bash
make website-preview
```

The command dispatches `.github/workflows/ok196-mkdocs-preview.yml` from `main`, waits for a successful **artifact-only** build, and prints the exact GitHub Actions run URL. The workflow checks strict MkDocs output and uploads downloadable HTML artifacts. To view the site locally, download the `ok196-unified-navigation-preview` artifact, extract it, and serve it from a local HTTP server. There is **no hosted preview URL** in this workflow.

```bash
make website-status
```

Shows the reviewed remote main revision and recent GitHub preview/release runs.

## Release to GitHub Pages

```bash
make website-release
```

This validates the exact reviewed remote main revision with a GitHub Actions preview artifact and a GitHub Pages **dry run**. There is **no interactive `OK` prompt**: running `make website-release` explicitly requests production publication. Production remains on [GitHub Pages](https://openkubes.org/) and still requires the protected GitHub Actions `release_confirmation` token, exact SHA, temporary `OK196_PAGES_RELEASE_ENABLED` switch and configured `github-pages` environment controls. Those release gates are automated by the script, not removed.

`make website-publish` uses the same verified build/dry-run and non-interactive release sequence, rather than trusting an old preview deployment.

No command changes your local branch, stashes local files, changes DNS, or mutates production infrastructure. Production publication still requires explicit authorization. Preview access requires GitHub Actions permission to dispatch the workflow.

### Failure handling

If a run fails, inspect the specific GitHub Actions run and the first failed build step. Do not rerun a blind deployment or bypass checks. When a production run is interrupted, check for running workflows and verify the release switch:

```bash
gh run list --repo openkubes/openkubes --workflow ok196-pages-release.yml --limit 10
gh variable get OK196_PAGES_RELEASE_ENABLED --repo openkubes/openkubes
```
