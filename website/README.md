# OK-196 — Stacked MkDocs homepage migration preview

**Preview-only.** This branch is based on the foundation spike PR #344, not on main.
PR #344 must be merged first, then this PR can be retargeted to main.
There is no deployment action; the existing production website and CNAME remain unchanged.

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
python website/scripts/stage-legacy.py
mkdocs build --strict
python website/scripts/preserve-homepage.py
python website/scripts/check-preview.py
```

The source HTML homepage is copied byte-for-byte **after** MkDocs builds.
This intentionally preserves the existing hero video, CTAs and CSS but means
the legacy homepage does not yet use the shared MkDocs theme/navigation.
The same old article routes are rendered to directories with index.html.
The artifact should be opened through a local web server, not as file:// URLs.

## Limitations and follow-up

- Only five current homepage articles are staged, not the complete URL inventory.
- Only two selected upstream documentation pages are included.
- Material search works for staged Markdown; the copied homepage is not indexed
  automatically or rendered with the Material navigation.
- Do not deploy this preview. Prior to cutover we need a complete URL inventory,
  linked-content checks, visual parity, shared navigation design, accessibility
  checks, and rollback approval.

## OpenKubes branding

`website/assets/openkubes-branding.css` and `.js` adapt the supplied OpenKubes
MkDocs branding V1 package. Assets are staged by `stage-legacy.py` and registered
in `mkdocs.yml`. The preserved HTML homepage loads them directly because it
replaces MkDocs' generated index. The compact philosophy block sits before the
existing hero in `docs/index.html`.

The static wordmark partial, `website/overrides/partials/openkubes-wordmark.html`,
is used by Material and both legacy navigation renderers. The homepage component
uses the same markup. Colors are sampled from `docs/openkubes-logo.png` (green,
blue and orange), rather than the package's approximate palette. Branding
remains visible without JavaScript. Screen readers receive all four principles
once; reduced-motion mode shows them all without animation. A keyboard-accessible
pause button controls typing; offscreen and hidden-tab animation is suspended.

Validate without deploying (after installing the pinned requirements and staging
the pinned upstream documentation described above):

```bash
PATH="$PWD/.venv/bin:$PATH" bash website/scripts/build-github-pages.sh
node --test website/tests/test_openkubes_branding.cjs
```

The build script runs the strict MkDocs build, homepage/navigation rendering,
legacy URL checks and production candidate checks. Do not use `make
website-publish` for local validation.
