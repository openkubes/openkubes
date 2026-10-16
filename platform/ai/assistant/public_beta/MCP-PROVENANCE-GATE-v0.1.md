# OK AI — MCP Provenance Receipt v0.2 (offline security prototype)

**Status: experimental library and offline tests ONLY. Not connected to
kagent, MCP runtime, live A2A probe, or public gateway. No live evidence
attestation is claimed. Public Beta HOLD.**

## Threat model / trusted boundary

Threats: model-generated fake source IDs; tampering with signed receipts;
reuse across requests, tenants/agents, index versions or tool responses;
out-of-date keys; unauthorized signature issuance; replay.

The offline helper `provenance_receipt.py` now signs a canonical v0.2 receipt
containing:
- Gateway-generated, unpredictable `request_id` and trusted MCP event ID.
- `question_sha256` for the exact original question.
- Explicit `issuer`, `audience`, `agent_id`, `tool=docs_search`.
- `arguments_sha256` of trusted MCP tool call arguments
  (exact question and bounded limit).
- `results_sha256` of the entire canonical validated tool response, plus
  `index_sha256` over the validated index snapshot.
- Bounded 1–8 actual `source_ids`, `issued_at`, `expires_at` (max 300 s).
- `key_id` and an HMAC-SHA256 signature using a distinct 32-byte key.

The verifier checks the signature with `compare_digest`, exact recipient/
agent/request/question identity, expiry/future skew, source membership,
actual trusted results/index hashes, citation set and an externally supplied
**atomic** one-time consumption callback. A missing or failed replay guard
fails closed. Multiple active verifier keys support a rotation interval.

## Critical conditions not implemented here

**Issuance identity is not authenticated by this library.** It is a protocol
helper, not the real signer: only a trusted MCP handler with authenticated
request context and actual returned tool results should issue receipts.
Never mint from a model answer, independent local retrieval, or arbitrary
JSON supplied by clients. The current Go kagent version has no verified
request propagation or event interception hook in this codebase.

**There is no production replay store.** The callback API must use durable,
cross-instance, atomic compare-and-set semantics, with expiry and
appropriate retention. Test-only in-memory callbacks are not sufficient.
Use a CSPRNG for distinct gateway request IDs and tool event IDs.

**No production secret distribution or issuer authentication.** Generate
32 random bytes from an OS CSPRNG; provision via scoped secret management,
not source control, prompt text, A2A messages or logs. Restrict key access
to trusted signer/verifier components, never the LLM. Separate keys per
environment, track `key_id`, securely rotate/revoke. HMAC verifiers hold
the same secret and can therefore forge receipts: use asymmetric signing
if consumers cannot belong to the same trust domain.

**No freshness attestation independent of caller-supplied wall-clock.**
Production must use trusted service clocks and bound clock skew/expiration,
not untrusted timestamps; handle revocation and replay on persistent storage.

**No model-use or semantic proof.** Even a legitimate receipt proves only
that a trusted tool handler observed retrieval under the bound context.
It cannot demonstrate the LLM read/passaged the tool results or prove that
a generated claim is supported or safe. Semantic evaluation remains separate.

**Offline source snapshots:** signing canonical results and index hashes
protects their integrity within this test boundary. Live version-pin,
content delivery, receipt transport and tool-call tracing are unimplemented.

## Offline tests

From `platform/ai/assistant`:

```sh
python3 -m unittest discover -s tests -v
```

Expected 103 tests (previous 87 plus 16 receipt tests). Includes negative
cases for result mutation, snapshot substitution, replay, expiry, key rotation,
cross-agent/audience context, forged input, and altered tool arguments.

## Release gate

Keep this PR Draft until local test confirmation and review. Do **not**
wire `issue_receipt` directly into the independent A2A probe: that would
manufacture apparently convincing provenance from unrelated retrieval.

Next separate work: assess kagent 0.9.12 / Go ADK verified hooks versus
gateway-owned retrieval to capture a real authenticated same-request MCP
tool event. Only then choose issuer lifecycle and implement the durable
ledger/secret distribution. No public beta rollout.
