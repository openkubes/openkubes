# Private context-only Gateway → A2A integration probe

**Status:** private live Option-B A2A format/source validation PASS for a
non-command question (2026-10-18); installation answer remains REJECT. No changes to Kubernetes manifests, existing
Agents, MCP services, model settings, website, public ingress or default routing.
**Public Beta HOLD.**

This is the next dependent slice after draft PR #392. It is deliberately
based on branch `feat/ok-ai-context-only-agent-lab` because that lab Agent
has not been merged into `main`. Keep the pull request base on the **lab
branch**, then retarget to `main` only after #392 merges.

## What it does

`public_beta/private_context_gateway_probe.py` performs one gateway-trusted
`DocsRetriever.docs_search(question, limit=8)` on one local validated index.
If empty, it rejects before attempting A2A. For valid hits it invokes
`build_context_envelope` + `encode_context_envelope`, then POSTs the
**exact bounded JSON** as one text part to the **fixed local**
`http://127.0.0.1:8083/api/a2a/openkubes-assistant/openkubes-docs-agent-context-lab/`
via a manually established Kubernetes controller port-forward.

The probe has no caller-configurable endpoint, does not follow redirects,
explicitly disables HTTP proxy usage, limits response size and timeout,
requires a completed A2A task, and validates the returned JSON through the
existing `validate_and_render(raw, same_request_hits, same_pinned_index)`.
It reports only sanitized status, source count, context hash and answer
character count. A positive result is **format and source-ID validation only**,
NOT proof of model context consumption, semantic grounding, network security,
deployment readiness or permission for public release.

The old `private_a2a_probe.py` hardcoded allowlist and the JSON/docs Agents
remain unchanged.

## Local offline regression tests (first)

From `platform/ai/assistant` on the **new integration branch**, run:

```sh
python3 -m unittest discover -s tests -p test_private_context_gateway_probe.py -v
python3 -m unittest discover -s tests -v
```

Any failures must be investigated before connecting to a live Agent.
These tests mock the A2A transport; they do **not** prove live model output.

## Private runtime gate — NOT automatically executed

**Only after offline tests pass and an operator agrees to run a private lab
probe**, the operator may use the already-existing read-only localhost
controller port-forward and the locally generated (untracked) index:

Terminal A:

```sh
kubectl --kubeconfig "$HOME/.kube/ok-kagent.yaml" \
  --context ok-kagent-admin@ok-kagent \
  -n kagent port-forward svc/kagent-controller 8083:8083 --address 127.0.0.1
```

Terminal B, from `platform/ai/assistant`:

```sh
python3 -m public_beta.private_context_gateway_probe \
  --index /tmp/openkubes-docs-index.json \
  --question "How do I install OpenKubes Local on macOS?"
```

Record only the sanitized JSON result, not the model's raw reply or document
snippets. A nonzero exit is a test failure, **not** reason to relax validators.
Prefer a question whose retrieved chunks are sufficient for a compact factual
non-command answer; the v0.1 structured contract deliberately rejects shell
commands and Markdown.

Correlate this exact invocation using private Hubble flow metadata for
Controller → context Agent TCP 8080 and context Agent → Ollama TCP 11434.
Verify actual policy/identity of the **real Agent** independently of the
prior temporary policy-matched probe. No public exposure. Stop if the
A2A endpoint, tool boundary, ingress/egress or identity differs from review.

## Known limitations / next gates

- Transport and schema/source metadata checks do not establish factual or
  claim-level semantic correctness.
- The private Context Envelope currently bounds questions to 500 characters;
  this does not implement the external proposed API's 4000-character,
  multi-turn contract.
- `ask_user` is an implicit kagent runtime tool; an interactive/pending
  A2A task must be rejected as incomplete.
- No gateway signing, replay ledger, session/authentication, rate limiting,
  streaming API, public website switch or production hardening.
- If live model replies are rejected, record a **fixed rejection reason**
  and investigate model/contract alignment; never auto-rewrite answers.
- #392 and this PR both remain Draft pending review, evidence, and explicit
  operator sign-off.

## Sanitized transport diagnostics (2026-10-17)

The initial private A2A probe returned the generic
`a2a_transport_or_task_error` consistently after **60.40 seconds** despite a
90-second Python client socket timeout. Hubble observed accepted
Controller-to-context-Agent TCP 8080 ingress. The Agent was
`Accepted=True` and `Ready=True`; runtime logs said
`execution context canceled` on repeated test attempts. A filtered Hubble
view of Agent-to-Ollama TCP 11434 did not show matching flows. These are
indicators, **not a proven root cause or proven absence of all model traffic**.

The probe now maps exceptions to sanitized codes, including
`a2a_http_504`, `a2a_http_502`, `a2a_http_error`,
`a2a_client_timeout`, `a2a_connection_error`,
`a2a_task_incomplete`, `a2a_protocol_error` and
`a2a_response_oversized`. It never echoes response bodies, exception
arguments or private payload content. No timeout or NetworkPolicy has been
changed.

**Next operator gate:** pull the changed branch and rerun offline tests
before another single live private probe. Observe both elapsed time and the
fixed reason code; if it remains exactly ~60 seconds, investigate controller
proxy timeout settings and upstream processing without increasing limits
blindly. Hubble network events alone do not establish the HTTP response code.

## Private live integration evidence (2026-10-18)

After the operator applied the specifically reviewed lab-only NetworkPolicy
changes, Hubble confirmed allowed CoreDNS egress and allowed Controller
session API egress TCP 8083 from the real Context Agent. Previously the
Controller session callback was dropped and produced JSON-RPC internal error
after approximately 60 seconds. The existing Ollama ModelConfig uses
`http://192.168.100.202:11434`.

The operator's real private A2A run for
`What is OpenKubes Local?` returned `PASS`, `accepted=true`,
`reason=format_and_source_ids_only`, `retrieved_chunks=8`,
`rendered_chars=189`, `semantic_grounding=UNVERIFIED`,
elapsed **11.305 seconds**, context digest
`5b781a6a0d3f16192cdc9dee720028c4b5933dfcc03840c96bb80b134f5baafb`.
This is an important **structural** integration milestone, not attested
same-request context consumption or semantic proof.

For `How do I install OpenKubes Local on macOS?`, the private live probe
returned `REJECT`, `reason=unsupported_text`,
`text_reject_category=command`, eight retrieved chunks, elapsed
**34.050 seconds** after the prompt-only refinement. No rejected text
was disclosed. The v0.1 answer validator intentionally disallows
command-looking model prose; this is a contract/product gap, not evidence
that the model's command was false.

## Proposed follow-on design: exact-source command rendering (NOT implemented)

Keep the existing model-generated prose contract unchanged. For requested
installation instructions, a separate trusted gateway path may extract
**whole fenced shell command blocks from the already verified and pinned
document index**, and render them alongside source-bound explanatory steps.
The model must never provide, edit, select via arbitrary paths/URLs, execute,
or transform executable commands. The gateway must enforce:

1. Authorized public-repository allowlist, immutable commit SHA, original
   chunk checksum, and exact source-ID matching within the same retrieval
   response. Never fetch latest or independently re-retrieve after inference.
2. Exact byte-preserving command blocks only when their complete start/end
   fences were captured in a trusted chunk; no concatenation across unrelated
   chunks, no snippets synthesized from natural-language instructions.
3. Tight size/count caps and fail-closed behavior for missing/ambiguous
   blocks, secret-like material, unsafe or destructive commands, or other
   unsupported syntax. These checks are additional to source provenance:
   being in the docs does not automatically make a command safe.
4. Distinguish **displayed reference commands** from execution; never execute,
   offer automatic execution, or accept commands from agent output.
5. Keep citations rendered exclusively from the pinned index. Every displayed
   command must clearly identify its precise source and revision. Establish
   appropriate offline security and provenance regression tests before a
   separate, explicitly reviewed implementation.

Do not relax `structured_answer.validate_and_render` to permit
model-authored commands. Design and security review are prerequisites.
Public Beta remains **HOLD**.

## Existing command-evidence reuse assessment (2026-10-18)

Implementation review confirms:
- `public_beta/command_evidence.py` is a **private-only structural
  diagnostic**: it classifies whole AI-supplied shell blocks as exact
  retrieved, elsewhere-in-index, whitespace-only or absent, and reports
  fixed categories and counts. Its module and tests explicitly say
  this is **not** an acceptance gate. Do not reuse its relaxed
  whitespace matching to authorize command rendering.
- `indexer.split_markdown` preserves complete fenced blocks and rejects
  oversized or unclosed fences. `docs_mcp.validate_index` provides
  immutable source metadata and content hashes. These are useful
  foundation components for a separately reviewed trusted renderer.
- The current live index explicitly allowlists
  `openkubes/ok-local/docs/tutorial-basic.md` and
  `docs/tutorial-capi.md`, plus selected public OpenKubes documents.
  It does **not** claim to ingest every README in all repos.
- `public_beta/structured_answer.py` still rejects command-like
  **model-authored** text and MUST remain strict.

Before implementation, the design review must define exact source-block
extraction and provenance binding, shell/code-fence language gating,
sensitive-command quarantine, multi-block ordering, bounded output,
source/revision display, and explicit non-execution guarantees.
Evidence from the existing `command_evidence_report` may guide tests
but cannot be treated as authorization. No command-rendering behavior
or production service has been implemented.

## Three-phase product roadmap reference

[OK-202 Jira architecture/MVP spike](https://kubernauts.atlassian.net/browse/OK-202)
explicitly specifies **Phase 1** public read-only Documentation Assistant;
optional **Phase 2** user-supplied redacted logs/manifests and read-only
diagnostics; **Phase 3** authenticated Agentic Operations via policy,
approval, runner, and evidence contracts without direct agent-initiated
Kubernetes mutations. These are future phase boundaries, not deployment
readiness claims.
