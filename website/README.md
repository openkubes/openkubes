# OK-196 — MkDocs foundation spike

This is **preview-only**. Production still uses the existing `docs/index.html` and
`docs/CNAME`; do not enable deployment from this pipeline.

## Local preview

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r website/requirements-mkdocs.txt
mkdir -p .ok196-sources
git clone https://github.com/openkubes/ok-local.git .ok196-sources/ok-local
git clone https://github.com/openkubes/ok-cluster.git .ok196-sources/ok-cluster
git -C .ok196-sources/ok-local checkout 60397cdb2630b0cd9cfbcb5d9a29fe2e38ce323e
git -C .ok196-sources/ok-cluster checkout a341f4ad4eff73e3cf7a69a38d1de8e2455e73a6
python website/scripts/build-docs.py
mkdocs build --strict
mkdocs serve
```

The pinned commits are a spike baseline, not an update mechanism. Upstream content remains
owned by the original repositories. The generated `.mkdocs-staging/` and
`.mkdocs-site/` are ephemeral; no source documentation is moved.

## Scope / limitations

- Only two selected upstream pages are included in this first smoke test.
- Theme and navigation are provisional; existing homepage, blog, hero media and URLs
  will be migrated only in separately reviewed PRs.
- The preview workflow uploads a build artifact, not a GitHub Pages deployment.
- Before cutover: full content manifest, internal/external link validation,
  URL compatibility inventory, accessibility and visual regression review.
