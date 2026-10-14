# Preview-first website publishing (OK-196)

Merge a reviewed website PR to `main`, then run:

```bash
make website-release
```

This single command uses the reviewed remote `origin/main` commit. It prepares and pushes Cloudflare preview from a **temporary Git worktree**, verifies the served SHA, executes a GitHub Pages **dry run**, and then prompts:

```text
Type OK to continue:
```

Type `OK` to approve the production stage. This is the **local UX confirmation only**: internally the GitHub Actions dispatch still uses `PUBLISH_OPENKUBES_ORG`, an exact expected commit SHA, the existing `OK196_PAGES_RELEASE_ENABLED` release switch and the `github-pages` environment controls. No production deployment runs before the confirmation.

Other commands:

```bash
make website-preview    # Synchronize and verify Cloudflare preview
make website-status     # Show the preview revision and recent release runs
make website-publish    # Publish a previously verified preview with explicit approval
```

The script does not stash local files, change your current branch, or publish uncommitted changes. Preview is served from Cloudflare Pages at https://preview.openkubes.org/; production uses GitHub Pages at https://openkubes.org/. No DNS changes are required.

**Authorization:** Preview publication requires rights to push to `website-preview`. The current production script additionally requires permissions to set the GitHub release variable, plus any configured GitHub Pages environment approval. Community contributors with only source-branch push access must ask a maintainer to release. Never grant production permissions solely to make the CLI work.

If a release fails or is interrupted, inspect GitHub Actions and verify no workflow remains active before an authorized administrator resets the release switch:

```bash
gh run list --repo openkubes/openkubes --workflow ok196-pages-release.yml --limit 10
gh variable get OK196_PAGES_RELEASE_ENABLED --repo openkubes/openkubes
```

For source ownership, navigation changes and the contributor editing workflow, see [How to update the docs](pages/community/how-to-update-docs.md).
