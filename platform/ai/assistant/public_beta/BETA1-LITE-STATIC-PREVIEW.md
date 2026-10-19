# Beta 1 Lite: smallest safe Preview-only website integration

**Status: Draft — no deployment, no public API, no generative model invocation. Public Beta HOLD.**

## Why the browser is static for this slice

The existing MkDocs website already embeds a floating UI demo only when the
hostname is preview.openkubes.org. The Beta 1 Lite HTTP prototype (#416) is
loopback-only, requires a server-side bearer token and is **not** hardened for
public browser traffic. Browser code must never receive this token or call the
private HTTP server directly.

This change therefore points the existing preview-only floating widget to
a **static curated response map**. This is a real clickable Preview UI
prototype, *not* a live Documentation Agent or connected gateway. No fetch,
XHR, WebSocket, telemetry, AI, model or internal API calls are made by this
widget. The old preview demo script is not loaded by the website override.

## Exact supported Q&A

Four exact phrasings (with case/whitespace/one terminal punctuation
normalization) map to two manually authored facts from the pinned public source.
Both answers are intentionally narrower than the earlier ungrounded
production-parity claim:

- What is OpenKubes Local?
- What is OK Local?
- What is ok-local?
- Does OpenKubes provide a local development environment?

Source pinned at openkubes/ok-local revision
60397cdb2630b0cd9cfbcb5d9a29fe2e38ce323e, docs/tutorial-basic.md.
Answers reference the documented fully automated local dev environment only.
Unsupported questions return a fixed explanation without made-up facts.
Rendering uses textContent, not user-controlled HTML, and the source link is
hardcoded to the pinned public GitHub URL.

**Known limitation:** The browser holds a static reviewed copy of the answer
catalog, not the runtime index-backed library. This is a distinct UI
demonstration artifact. Before public API launch, avoid maintaining divergent
independent copies: connect only through a reviewed same-origin authenticated
proxy/backend; never turn the current local bearer-token prototype into a
browser endpoint.

## Review / offline tests

From platform/ai/assistant on this branch:

    python3 -m unittest discover -s tests -p 'test_lite_static_preview.py' -v
    python3 -m unittest discover -s tests -v

Seven static preview tests now expected (including MkDocs staging/asset check);\napproximately 193 total if the previously operator-verified 192 remain unchanged.\nThe new build-integrity change is not yet operator-verified.

## Release gates

1. Review fixed copy/source, 4 approved phrasings, and preview-only visibility.
2. Verify the MkDocs staging/build includes the new
   website/assets/ok-ai-lite-preview.js asset.
3. Review compiled site: Preview hostname loads the Lite script; production
   hostname does not instantiate the widget; no secret or internal endpoint
   appears in page JS. Existing website/pages/ai/chat-preview.md remains
   a separately labeled legacy visual demo for now.
4. Do NOT merge or preview-publish without separate maintainer approval.
   The existing make website-preview flow publishes reviewed main commits only,
   not an arbitrary Draft PR branch. Preview may be public on the internet;
   all output is therefore limited to pre-reviewed public content.
5. Public production rollout still requires its own product/security sign-off,
   actual public entrypoint controls if a backend is later connected, request
   limits, observability, privacy review, operational rollback and E2E evidence.

**No Kubernetes resources, Cloudflare settings, DNS, or website deployment have
been changed.**

## Build-staging finding (2026-10-19)

Repository review found that `website/scripts/stage-legacy.py` originally copied
only the old demo assets; the new Lite JavaScript was therefore missing from
the MkDocs output despite the source-level tests passing. The Draft PR now
copies `ok-ai-lite-preview.js`, `website/scripts/check-preview.py` rejects
output lacking it, and one new static test verifies both contracts. The
maintainer still needs to run the complete website build with pinned
`.ok196-sources` checkouts. The legacy homepage is not Material-rendered:
its `docs/index.html` is restored separately, so the Lite floating widget
is **not** guaranteed to appear there; test a Material subpage such as
`/ai/` on the preview hostname. Do not claim homepage-global coverage.
