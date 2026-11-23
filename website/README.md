# OpenKubes website builds

GitHub Actions produces downloadable preview artifacts. Reviewed production builds are published through GitHub Pages. See [the publishing workflow](PUBLISH-FLOW.md).

## Local validation

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r website/requirements-mkdocs.txt
mkdir -p .ok196-sources
git clone https://github.com/openkubes/ok-local.git .ok196-sources/ok-local
git clone https://github.com/openkubes/ok-cluster.git .ok196-sources/ok-cluster
git -C .ok196-sources/ok-local checkout 60397cdb2630b0cd9cfbcb5d9a29fe2e38ce323e
git -C .ok196-sources/ok-cluster checkout e73de4f4c4e7b421785ded992881a6074005c6bd
bash website/scripts/build-github-pages.sh
```

The local build stages the pinned documentation, runs MkDocs in strict mode,
restores the legacy homepage and article URLs, and validates the preview and
production output in `.mkdocs-site/`. Serve that directory over local HTTP to
review the candidate.

## OpenKubes branding

`website/assets/openkubes-branding.css` and `.js` adapt the supplied OpenKubes
MkDocs branding V1 package. Assets are staged by `stage-legacy.py` and registered
in `mkdocs.yml`. The preserved HTML homepage loads them directly because it
replaces MkDocs' generated index. The compact philosophy block sits before the
existing hero in `docs/index.html`.

The static wordmark partial, `website/overrides/partials/openkubes-wordmark.html`,
is used by Material and both legacy navigation renderers. The homepage component
uses the same markup. The shared CSS defines the exact per-letter palette supplied to match the
wordmark on kubernauts.de. Branding
remains visible without JavaScript. Screen readers receive all four principles
once; reduced-motion mode shows them all without animation. A keyboard-accessible
32 × 32 icon button controls typing and resumes from the current position; offscreen and hidden-tab animation is suspended.

Validate without deploying (after installing the pinned requirements and staging
the pinned upstream documentation described above):

```bash
PATH="$PWD/.venv/bin:$PATH" bash website/scripts/build-github-pages.sh
node --test website/tests/test_openkubes_branding.cjs
```

The build script runs the strict MkDocs build, homepage/navigation rendering,
legacy URL checks and production candidate checks. Do not use `make
website-publish` for local validation.

## Console homepage gallery

The section in `docs/index.html` comes from the user-supplied
`openkubes-console-carousel-codex-complete-v2.zip`, following its README. It sits
between the unchanged installer announcement and four-cluster animation. The
original English copy, inline visual styling, screenshot order, Open Source
panel, links and responsive grid are retained.

Integration changes: explicitly inherit left alignment within the centered hero
header and avoid the site's generic section divider; use relative thumbnail URLs;
move the existing modal behavior into `website/assets/openkubes-console-carousel.js`;
resolve modal URLs from those thumbnails for path-prefix hosting; add visible
keyboard focus, a modal backdrop, and polite image-title announcements. The native
dialog preserves Escape, background inertness and focus restoration; an explicit
Tab/Shift+Tab boundary keeps keyboard focus cycling through modal controls. Previous/next
buttons and arrow keys wrap around the three original images; there is no autoplay.

The three WebPs in `website/assets/images/console/` are byte-identical to the
package. `stage-legacy.py` copies them and the gallery CSS/JS into the built site.
The homepage loads its gallery assets directly; other pages do not initialize it.

Run `node --test website/tests/test_*.cjs` for typewriter and gallery behavior,
and the full non-deploying build command above for staging, placement, assets,
legacy routes and production candidate checks. Browser QA also covers native
modal focus/Escape behavior and responsive layouts.
