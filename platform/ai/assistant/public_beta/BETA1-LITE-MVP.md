# OK AI Beta 1 Lite — frozen MVP scope (offline candidate)

**Status: DRAFT / NOT PUBLIC / NO DEPLOYMENT / Public Beta HOLD.**

## Product contract

- A small, curated single-turn Documentation Q&A experience, **not a free-form generative chatbot**.
- This first slice recognizes exactly four question phrasings concerning **whether OpenKubes provides a local development environment and what ok-local is** (see immutable `QUESTIONS` in `curated_lite.py`).
- The answers are static, manually reviewed against the literal statement in `openkubes/ok-local/docs/tutorial-basic.md`, and intentionally do **not** claim production parity or a single-node topology for ok-local.
- The source must be an explicitly allowlisted, intact document chunk from a validated immutable-commit index and contain the exact support sentence. Source URLs come from that index, never from user or model text.
- All other questions return `UNSUPPORTED` with a plain safe explanation. Missing or ambiguous supporting evidence returns `UNAVAILABLE`. No shell commands, source snippets, model inference, Kubernetes operations, A2A calls, chat memory or user-selected links.
- This is an offline answer library only. **It does not implement a public HTTP endpoint, UI, rate limiting, authentication, abuse controls, production telemetry or rollout.**

## Deliberate trade-off

Beta 1 Lite favors **provenance + curated correctness over coverage**. It will not pretend to answer open-ended questions or guarantee that a fuzzy match is safe. The first four phrasings deliberately cover one narrow factual topic. After successful human review, expand through a similarly reviewed catalog of bounded topics and pinned source evidence; do not auto-ingest or auto-approve model outputs.

## Test locally

From `platform/ai/assistant` on `feat/ok-ai-beta1-lite-curated-offline`:

    python3 -m unittest discover -s tests -p 'test_curated_lite.py' -v
    python3 -m unittest discover -s tests -v

Nine new focused tests; approximately 175 total if the previously reported 166 remain unchanged. **Not verified yet on the maintainer's machine.**

The current pinned index used in the private lab is from `ok-local` revision `60397cdb2630b0cd9cfbcb5d9a29fe2e38ce323e`. Index freshness and source suitability should be reviewed before public use. The separately ongoing `ok-local` documentation PR #6 does not automatically update this index.

## Release blockers still required

1. Human review and approval of each fixed answer + exact source quote (including approved copy text and link UX).
2. Fail-closed integration into an actual backend with request body bounds, authentication or protective access design, per-client rate limits, anti-abuse, strict CORS/CSRF policy as applicable, no direct public A2A/Ollama access, and a quick disable switch.
3. Data-handling review (no raw questions by default in logs), baseline health/availability monitoring and response error handling.
4. Preview UI and private/negative end-to-end tests; independent operational/security Go/No-Go before production exposure.

**No merge, deployment, public website change or cluster modification was performed.**
