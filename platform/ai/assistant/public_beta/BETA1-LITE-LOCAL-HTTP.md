# Beta 1 Lite — private HTTP boundary (Draft)

**NOT PUBLIC-READY. Public Beta HOLD.** Standard-library local-only proof for the curated offline Q&A library.

## Contract

- POST `/api/beta1-lite/question`, body JSON containing **only** `question` (max 1024 request bytes).
- Mandatory private bearer token supplied only through `OPENKUBES_BETA1_LITE_TOKEN`, 32–256 characters.
- Bind strictly to `127.0.0.1`, never `0.0.0.0`; no CORS wildcard or direct browser/public client access.
- Sliding-window limit of 20 authenticated requests per minute **per single local server process**, not a distributed or per-user public limiter.
- Prevalidated pinned docs index and existing exact-match curated answers; nonallowlisted question returns `UNSUPPORTED`; invalid/tampered index fails closed.
- No model, Agent, Kubernetes, shell execution, dynamic retrieval, prompt injection interpretation, or public website integration. No access logs containing questions, tokens, snippets or answers.

## Local tests first

From `platform/ai/assistant` on branch `feat/ok-ai-beta1-lite-local-http-lab`:

    python3 -m unittest discover -s tests -p 'test_curated_lite_http.py' -v
    python3 -m unittest discover -s tests -v

Expected 11 focused new tests; approximately 186 total after the previously reported 175. Counts **not yet verified**.

## Optional private manual smoke test

Only if wanted, from `platform/ai/assistant`, on a trusted machine, outside a publicly forwarded environment:

    export OPENKUBES_BETA1_LITE_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
    python3 -m public_beta.curated_lite_http --index /tmp/openkubes-docs-index.json --port 8765

In another local terminal, use the same secret without writing it to Git history. Do **not** paste the token into GitHub, browser JS, CI logs or the chat. For this lab only, a separate local client may POST with an `Authorization: Bearer ...` header.

Stop the local server with Ctrl+C. This tool does not deploy anything or expose an ingress.

## Explicit production blockers

The HTTPServer implementation is intentionally single-process and synchronous; it is **not** a hardened public HTTP edge. Missing capabilities include TLS ingress and authenticated browser session/proxy design, multi-user distributed abuse/rate limiting, timeout/concurrency protections, origin/CSRF controls where applicable, production secret handling and rotation, safe health/metrics/alerting, availability/restart/rollback, privacy sign-off, preview E2E, and operator security review.

Do not publish or tunnel this port, hardcode the bearer token client-side, or claim a public endpoint is ready. A separate reviewed production gateway must enforce all public edge controls.
