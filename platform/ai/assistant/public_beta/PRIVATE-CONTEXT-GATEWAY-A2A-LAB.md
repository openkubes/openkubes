# Private context-only Gateway → A2A integration probe

**Status:** implementation + offline regression tests; **not yet executed against
the live context-only Agent**. No changes to Kubernetes manifests, existing
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
