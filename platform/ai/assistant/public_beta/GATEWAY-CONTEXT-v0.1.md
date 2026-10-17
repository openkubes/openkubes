# OK AI — Gateway Context Envelope v0.1

**Offline-only proof of contract.** This does NOT deploy a new agent,
change any kagent runtime or private Kubernetes resources, or expose an HTTP
endpoint. Public Beta HOLD.

## What the module does

`public_beta/gateway_context.py` implements
`build_context_envelope(question, retrieval, index)` and
`encode_context_envelope(envelope)`.

- Accepts an already retrieved result from a **trusted gateway-controlled**
  `DocsRetriever` invocation. It does not autonomously re-run retrieval.
- Checks the reviewed index with `validate_index`, matches every returned
  result exactly to its pinned source record, and rejects extra fields,
  duplicate IDs and missing sources.
- Produces deterministic JSON with question, source ID, exact snippet,
  SHA-256 snippet digest, canonical retrieval digest and index digest.
- Hashes the exact payload serialization as `context_sha256`, rejects malformed
  questions and enforces bounded source counts/response size.
- Encodes untrusted snippet strings as **JSON values** rather than concatenated
  prompt instructions. JSON encoding alone is **not** a prompt-injection defense.

## What it deliberately does NOT do

- No A2A transport, agent configuration, MCP operation or network I/O.
- No request ID, trusted issuer, HMAC signature, replay ledger or delivery
  receipt. Hashing only detects accidental or adversarial modifications when
  the expected digest comes from a trusted channel.
- No proof that the model read or used the delivered context.
- No semantic checking of generated factual claims.
- No attempt to convert gateway retrieval into a false MCP tool-call receipt.
  `provenance_receipt.py` v0.2 remains a separate offline **MCP-specific**
  protocol; Option B needs its own versioned gateway-retrieval evidence type.

## Run tests

In `platform/ai/assistant`:

```sh
python3 -m unittest discover -s tests -v
```

Expected **115** tests if the preexisting suite remains at 103; 12 new
offline envelope regression tests. No deployment is required.

## Follow-up PR

After review, create a separate **context-only, no-tools** kagent Agent
manifest and perform a server-side Kubernetes dry-run, without changing the
existing docs Agents. The new Agent must have no MCP or Kubernetes tools and
must be isolated by NetworkPolicy. Only with explicit deployment approval
should the private gateway start passing these envelopes over allowlisted A2A.

The gateway MUST preserve independent statuses for trusted retrieval,
context-delivery attempt/completion, structured answer validation, and
semantic-grounding uncertainty.
