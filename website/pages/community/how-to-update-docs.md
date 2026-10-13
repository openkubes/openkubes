# How to update the docs

**OpenKubes documentation is open source and Git-driven.** Every public change starts with a reviewed pull request. The website is built using MkDocs Material; Cloudflare hosts the preview, and GitHub Pages hosts production.

## Find the source of the page

Not every page is authored in the same repository. Edit the **original source**, not the generated `.mkdocs-staging/` or `.mkdocs-site/` output.

| Website content | Source of truth |
| --- | --- |
| [Getting Started](/getting-started/) | [`openkubes/openkubes/docs/getting-started/README.md`](https://github.com/openkubes/openkubes/blob/main/docs/getting-started/README.md) |
| [OK AI](/ai/) and [Community](/community/) | [`openkubes/openkubes/website/pages/`](https://github.com/openkubes/openkubes/tree/main/website/pages) |
| Blog and older technical articles | [`openkubes/openkubes/docs/`](https://github.com/openkubes/openkubes/tree/main/docs) |
| OpenKubes Local tutorials | [`openkubes/ok-local/docs/`](https://github.com/openkubes/ok-local/tree/main/docs) |
| Cluster-specific documentation | [`openkubes/ok-cluster/docs/`](https://github.com/openkubes/ok-cluster/tree/main/docs) |

**Important:** External tutorials are imported selectively at pinned revisions. A change in `ok-local` or `ok-cluster` does not automatically appear on this website. A separate website PR must update the pinned revision or imported page list, as appropriate.

## 1. Propose a documentation change

You can use GitHub's file editor or your local clone:

```bash
git clone https://github.com/openkubes/openkubes.git
cd openkubes
git switch -c docs/update-my-page
# Edit the source Markdown file
git add path/to/your-file.md
git diff --cached --check
git commit -m "docs: improve documentation"
git push -u origin docs/update-my-page
gh pr create --base main --fill
```

If you do not have write access, fork the repository and submit a pull request from your fork instead. For docs owned by another OpenKubes repository, submit the PR there.

Reviewers check correctness, links, formatting and security. Never include secrets, private endpoints, customer data or unredacted operational evidence.

## 2. Review and merge

A maintainer reviews the PR. After approval, merge to `main`. The website does not publish unreviewed local changes or feature-branch drafts.

To change the **left navigation**, update [`mkdocs.yml`](https://github.com/openkubes/openkubes/blob/main/mkdocs.yml). For a new website page, add the Markdown source under `website/pages/` and ensure [`website/scripts/stage-legacy.py`](https://github.com/openkubes/openkubes/blob/main/website/scripts/stage-legacy.py) stages it before linking from the navigation.

## 3. Preview changes

An authorized contributor with push access to the preview branch can run:

```bash
make website-preview
make website-status
```

Preview: **[preview.openkubes.org](https://preview.openkubes.org/)**

The publishing script works from the reviewed **remote `main`** revision through a temporary Git worktree. Local uncommitted edits are not included, and there is no need to stash them.

## 4. Release to production

For maintainers with release permissions:

```bash
make website-release
```

The command updates preview, verifies the exact deployed commit, runs a GitHub Pages dry run and then asks:

```text
Type OK to continue:
```

Enter **`OK`** to approve the production stage. The workflow retains its internal revision, repository-variable and GitHub Pages environment protections. Typing `OK` is **not** a substitute for the required GitHub permissions or environment approval.

Production: **[openkubes.org](https://openkubes.org/)**

You may also use `make website-publish` for an already verified preview. Contributors without production privileges should request a release from a maintainer rather than attempting to change repository release gates.

## Need help?

Open an [issue](https://github.com/openkubes/openkubes/issues), start a [discussion](https://github.com/openkubes/openkubes/discussions), or join [Kubernauts Open Hours](https://www.meetup.com/kubernauts/).

See also the [publishing workflow documentation](https://github.com/openkubes/openkubes/blob/main/website/PUBLISH-FLOW.md).
