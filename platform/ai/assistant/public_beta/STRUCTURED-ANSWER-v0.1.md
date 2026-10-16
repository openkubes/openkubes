# OK AI Structured Answer Contract v0.1 (experimental)

**Status: offline design prototype. NOT a production policy, public gateway,
semantic verifier, or activated kagent response mode.** Public Beta remains HOLD.

The current model sometimes emits unexpected Markdown (inline code, bare URLs,
fenced blocks) despite prompt restrictions. This lab-only alternative asks for
a **small JSON object**, then parses it strictly and constructs Markdown
without accepting model-supplied links or Markdown syntax.

## Contract

Expected shape:

```json
{
  "version": "0.1",
  "steps": [
    {"text": "Read the installation prerequisites in the guide.",
     "source_ids": ["0123456789abcdef"]}
  ]
}
```

The ID shown above is illustrative, not a usable example source. Actual IDs
must come from the **gateway-retrieved** index metadata.

See `structured_answer.schema.json` for the intended JSON Schema, and
`structured_answer.py` for the enforced subset. Every step has bounded
plain text and one to three source IDs. There are one to six steps.
No model-authored URL, HTML, Markdown markup, code block, shell command-looking
text, arbitrary property or unsupported source identifier is permitted.
No invalid payload is repaired automatically.

The deterministic renderer creates numeric steps and citations using only
canonical URLs from validated index metadata, and passes the final Markdown
through the **existing strict answer integrity validator**. Exceptions must
map to a fixed fail-closed response when integrated into a private gateway.

## Test

From `platform/ai/assistant`:

```sh
python3 -m unittest discover -s tests -v
```

These are *offline fixture tests*. This PR does not change the deployed
agent prompt, GitOps manifests, localhost live gateway, kagent A2A probe,
Cloudflare edge or Floating Chat widget.

## Open blockers (explicit)

1. **Actual tool provenance**: Independent gateway retrieval alone does not
   prove which MCP results the model saw. Source IDs must be bound to the
   *actual same-request* tool transcript or trusted gateway-owned retrieval.
2. **Semantic grounding**: Syntactically valid steps with valid source IDs can
   still contain unsupported or misleading claims. Add evidence per claim,
   dedicated fact/command evaluation and fail-closed abstention before use.
3. **Safe command generation**: v0.1 intentionally does not support commands.
   If introduced later, whole command blocks need exact retrieval and policy
   proof; never treat syntax validation as operational authorization.
4. **Model integration**: Real kagent structured-output support is unverified;
   test with an isolated private agent before enabling any application path.
5. **Gateway security**: No external API deployment, authentication, ingress,
   verified streaming, privacy release gate, rate limiting or CVE clearance.

No public rollout, no silent auto-rewrite of rejected Markdown, and no change
to the existing answer validator are part of this PR.
