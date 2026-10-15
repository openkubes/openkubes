# OK AI loopback-only gateway demo

**Not a public service, not a live kagent integration.** This prototype exists to test gateway-side retrieval and answer validation independently of the LLM. Its built-in response generator is **static** and labels its answers as demo. It must not be deployed or connected to `openkubes.org` as an AI service.

## Run locally

From `platform/ai/assistant` with Python 3.10+:

```sh
python3 -m unittest discover -s tests -v

# Reuse the previously built, SHA-pinned index:
python3 -m public_beta.local_gateway --index /tmp/openkubes-docs-index.json
```

The local server binds **only** to `127.0.0.1:18081` (not configurable to a wildcard address). From a second terminal:

```sh
curl --fail-with-body --silent --show-error \
  --header 'Content-Type: application/json' \
  --data '{"question":"How do I install OpenKubes Local on macOS?"}' \
  http://127.0.0.1:18081/api/chat
```

Expected: HTTP 200 JSON with `"demo": true`, a static response and retrieved, pinned source metadata. A known-unmatched query gets HTTP 422 `no_verified_source`. Use Ctrl-C to stop.

## Isolation and security boundaries

- The gateway loads a locally reviewed and validated index; it performs independent retrieval for each question rather than accepting client-supplied citations.
- The prototype runs a fail-closed check from `answer_integrity.py` before returning its static answer.
- No network fetch, model call, kagent call, MCP HTTP client, cluster access, credentials, streaming or deployment.
- The API rejects unexpected request keys, non-JSON content types and oversized bodies; access logging is disabled.
- HTTP on localhost is **not** public API security. There is no authentication, rate limit, browser origin policy, TLS, request queue, timeout envelope or operational hardening.
- Source passages may contain instructions; the validator only checks syntactic provenance, not semantic correctness or command safety.
- Validator implementation is inherited from the **unmerged draft PR #377**. Review these PRs together or rebase in order. The branch targets PR #377's head for a stacked diff.

**Release status: HOLD.** Public production requires securely bound retrieved evidence per request, robust structured response/citation support, independent semantic validation, CVE clearance and gateway policy controls.
