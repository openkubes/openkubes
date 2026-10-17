# OK AI — Gateway-owned retrieval & evidence delivery (architecture spike)

**Status:** proposed, design only. No deployment, no public traffic, no kagent
fork, no production security claim. **Public Beta: HOLD.**

## Decision

Choose **Option B**: OpenKubes controls retrieval, context assembly, evidence
and answer validation in a trusted private gateway. Keep upstream kagent
unmodified. Existing `openkubes-docs-agent` and
`openkubes-docs-agent-json` remain unchanged.

**Important distinction:** gateway retrieval proves which snapshot was
retrieved. A successful A2A transport response proves a request was accepted
and responded to, **not** that every supplied passage was read by the LLM,
used in its reasoning, or semantically supports the answer.

## Minimal private flow

1. Gateway authenticates the caller (future), validates a bounded question,
   creates a fresh CSPRNG 128-bit `request_id`, and pins one validated index.
2. Gateway calls **its own trusted** `DocsRetriever.docs_search(question,
   limit=8)` exactly once for the request. The result is the authoritative
   allowlist for this request. If empty, fail closed: `NO_SOURCES`.
3. Gateway assembles a bounded **context envelope** containing the question,
   an unambiguous request marker, and the retrieved `source_id` and `snippet`
   pairs. Tool text is always *untrusted data*, delimited from instructions.
   Never include raw unreviewed web, logs, credentials, model-supplied URLs,
   or a signing key. Enforce size/encoding limits before transmission.
4. Gateway delivers the envelope to a NEW **isolated context-only kagent Agent**
   over the existing loopback A2A route. **This agent must expose no MCP,
   Kubernetes, network, shell, or subagent tools.** Existing agents are not
   modified; no new Agent is deployed in this design PR. Merely instructing
   a tool-enabled agent not to call MCP is NOT sufficient. Confirm the kagent
   CRD permits an empty tool list by server-side dry-run before deployment.
5. Context-only agent returns Structured Answer Contract v0.1 JSON only.
   The gateway independently validates with `validate_and_render(raw,
   retrieved, pinned_index)`; only canonical index URLs are rendered.
   Missing, invented or mismatched source IDs fail closed.
6. Gateway records **two separate local assertions**: (a) retrieved and
   validated exact source snapshot, and (b) successfully submitted context
   envelope to an allowlisted A2A endpoint with completed task response.
   Record request ID, snapshot hash, context hash, A2A result status,
   timestamps and error reason codes. A2A success does **not** certify
   model consumption.
7. Security/quality gates reject failures, malformed JSON, unsupported source
   references, document poisoning patterns, timeouts, oversize responses and
   policy-restricted output. A distinct semantic-grounding gate remains
   required before public beta.

### Trust boundaries

| Boundary | Owned by | Evidence / prohibition |
| --- | --- | --- |
| Corpus | OpenKubes indexer | reviewed allowlist, pinned revisions, chunk SHA256 |
| Retrieval | Trusted gateway | exact results and index snapshot digests |
| Context delivery | Gateway -> allowlisted A2A | hash of envelope + bounded completed A2A response; no inferred model use |
| Model | Isolated no-tools kagent | untrusted JSON suggestions, never signs evidence |
| Validator | Gateway | schema, source allowlist, canonical URL, syntax checks |
| Signing | Trusted issuer only | keys never sent to kagent/LLM/client |
| Semantic correctness | Separate future gate | not implied by receipts or A2A completion |

## Receipt protocol v0.2 compatibility — critical caveat

`public_beta/provenance_receipt.py` v0.2 declares the signed tool as
`docs_search` and describes a receipt from an actual trusted MCP tool
handler. In Option B, retrieval moves into the gateway. **Do not relabel
gateway retrieval as an actual MCP tool call.** The v0.2 helper is NOT yet
appropriate for signing gateway-retrieval evidence as MCP provenance.

A **separate versioned gateway-retrieval evidence type** (new version/type)
must bind request ID, gateway issuer/audience, exact query, pinned index hash,
full returned source/content hashes, context-envelope digest, A2A delivery
state and expiry. Restrict signing to the gateway's trusted retrieval path.
Keep the old MCP receipt v0.2 for actual MCP calls only. Do not let a single
untyped `PASS` conflate retrieval, delivery and semantic support.

Suggested statuses (distinct):
- `RETRIEVAL_VERIFIED`: trusted gateway successfully looked up and validated
  the pinned source snapshot.
- `CONTEXT_SUBMITTED`: bounded payload was sent to the allowlisted private
  A2A endpoint; proof of API exchange, not model internal consumption.
- `FORMAT_AND_SOURCE_IDS_PASS`: response parsed and all citations belonged
  to supplied sources; NOT semantic endorsement.
- `SEMANTIC_GROUNDING_UNVERIFIED`: mandatory until an additional gate exists.

## Safety and deployment conditions

- A2A endpoints remain explicit loopback-only allowlists with redirect
  rejection, request/response size bounds, fixed timeouts and no public ingress.
- Context-only Agent must be a **separate** Agent and deployment from
  existing MCP-enabled Agents. No kubectl apply until reviewed/dry-run.
- Confirm that runtime-level implicit tools (e.g. ask-user) cannot provide
  additional fetch/cluster capabilities. Pin network egress for the new Agent
  to Ollama and required kagent control services; deny access to docs MCP.
- Strictly distinguish transport success from execution provenance. Treat
  document snippets as prompt-injection-capable adversarial data.
- Never log raw prompts, retrieved excerpts, model replies, credentials or
  cryptographic secret keys. Bound diagnostic counters only.
- No Kubernetes or public website change in this spike.

## Proposed implementation slices

**PR 1 — Offline context-envelope contract and tests.** Build
`public_beta/gateway_context.py` with pure deterministic validated-context
assembly (no network/signing). Tests cover oversized contexts, malformed
source/index, prompt-injection separation, stable hashing and escaping.

**PR 2 — Isolated no-tools lab Agent.** Manifest only with ModelConfig
`docs-ollama`; Kubernetes server-side dry-run, read-only network-policy
review, no rollout until explicit operator approval.

**PR 3 — Private gateway A2A experiment.** Deliver the envelope to the
isolated no-tools Agent; deterministic rendering and separate retrieval/
delivery/formatted-response statuses. Run unit + integration quality gates.

**PR 4 — Gateway evidence attestation + durable replay store.** Different
receipt type from MCP v0.2; controlled keys, expiry, atomic replay prevention,
privacy review. Semantic testing is a separate release blocker.

## Acceptance criteria for this design

- No changes to the two running Agents or production/static widget.
- A single authoritative retrieval result drives both context and citations.
- Agent cannot independently invoke `docs_search` (tool isolation, not prompt).
- Fake citations and wrong index/response return explicit rejected statuses.
- No claim that content delivery proves LLM usage or semantic truth.
- Gateway retrieval not mislabeled as a real MCP call or v0.2 MCP receipt.
- Dry-run and rollout are separate operator-controlled steps.

## Existing reference implementation points

- `docs_mcp.py` — validated pinned documentation and DocsRetriever.
- `public_beta/structured_answer.py` — source-bound JSON validation.
- `public_beta/private_a2a_probe.py` — allowlisted loopback A2A exchange.
- `kagent/openkubes-docs-agent-json.lab.yaml` — existing tool-enabled agent,
  **not** suitable unchanged for the no-tools context lab.
- `public_beta/provenance_receipt.py` — MCP-only experimental receipt v0.2,
  **not** a gateway retrieval signing API.
