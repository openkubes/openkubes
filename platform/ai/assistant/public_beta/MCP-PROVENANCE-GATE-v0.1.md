# OK AI — MCP Provenance Gate v0.1 (offline proof-of-contract)

**Status: experimental library and offline tests ONLY. Not connected to kagent,
the existing MCP server, or the live A2A probe. Do not treat an offline PASS
as proof of tool usage or semantic grounding. Public Beta remains HOLD.**

## Why

The private JSON agent passed `structured_answer.py` using independent local
retrieval, but this does not prove that the agent invoked `docs_search` on the
same request or saw the same documents.

`provenance_receipt.py` specifies a small, authenticated receipt boundary:
- `request_id`: a random 128-bit request identifier assigned by a **trusted**
  gateway, not by the model.
- `question_sha256`: binds the receipt to that specific question.
- `tool`: exactly `docs_search`.
- `source_ids`: the retrieved source IDs recorded by the **trusted**
  MCP tool handler.
- `signature`: HMAC-SHA256 over canonically encoded fields, verified
  with a distinct secret key known only to trusted components.

`verify_receipt` rejects missing, invalid, tampered, mismatched, or
cross-request receipts and citations outside the signed source IDs.
`issue_receipt` is a **fixture/protocol helper**, not authorization to
mint receipts from data supplied by the model or the independent
`DocsRetriever` running in the probe.

## Important trust and security limitations

1. **No runtime instrumentation yet**. No authenticated request-id propagation
   from A2A gateway to MCP, no attested tool-call receipt in live responses,
   no kagent tool-transcript extraction. The isolated JSON agent is unchanged.
2. **No model-consumption proof**. Even an authentic receipt establishes only
   that a trusted MCP handler observed retrieval, not that the LLM used it.
3. **No semantic proof**. Signing source IDs does not establish that a sentence
   is true, supported by a snippet, or safe to execute.
4. **No production key management**. Test key is hardcoded in test fixtures
   only. Production would need separate restricted credentials, key rotation,
   replay prevention, expiry, and no raw question/document logging.
5. **No stable document snapshot guarantee** beyond the existing index
   validation. Future receipts should bind to index digest and actual returned
   source contents, not merely IDs.
6. **Not integrated as a release gate**. The live `private_structured_a2a_probe`
   retains its explicit provenance warning. It must not report VERIFIED
   until real same-request instrumentation and trust validation exist.

## Offline check

From `platform/ai/assistant`:

```sh
python3 -m unittest discover -s tests -v
```

Expected count is **99** (87 existing + 12 new tests), subject to future
test additions. No Kubernetes changes or public network paths are introduced.

## Next implementation decision (separate PR)

Prefer a trusted gateway-owned docs retrieval step with an authenticated,
per-request execution context or a narrow MCP middleware/event hook that
records actual request-to-tool-result mappings. Verify supported kagent/Go ADK
hooks before choosing an instrumentation method. Bind receipts to actual tool
results, index snapshot digest and fresh gateway request IDs. Do not accept
provenance fields supplied by an LLM as attestation. Audit for privacy and
replay resistance before any production use.
