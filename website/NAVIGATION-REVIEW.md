# OK-196 — Preview navigation review (PR #346)

This iteration is **preview-only**. The unchanged public homepage at
`docs/index.html` remains the source of truth, and publishing via GitHub
Pages is neither enabled nor modified.

## Design

- A dark branded horizontal primary navigation is injected into the built
  homepage **after MkDocs builds**. It links Home, Features, Architecture,
  Blog, Docs and Community.
- For now, Features and Architecture target existing homepage sections.
  A later PR may introduce dedicated destination pages.
- Material for MkDocs provides the same top-level information architecture
  for documentation and articles through `mkdocs.yml`. A shared dark
  navigation palette and header link style are applied through a CSS asset.
- Existing blog permalinks and the hero-video source markup are retained.
- Search works for the Markdown documentation and blog. The legacy HTML
  homepage is not in the MkDocs search index yet.

## Browser acceptance

Serve the extracted artifact with `python3 -m http.server 8000` and review
`/`, `/docs/`, and `/agentic-operations-reference-architecture/`.
Check mobile width, keyboard focus, blog navigation, home anchors, video
autoplay fallback, and links.

## Not yet complete

Material's built-in header is not pixel-identical to the legacy homepage bar;
this is a coherent brand treatment, not the final unified theme. Dedicated
Features/Architecture pages, broader documentation integration, URL inventory,
automated accessibility checks and a production cutover plan remain follow-ups.
