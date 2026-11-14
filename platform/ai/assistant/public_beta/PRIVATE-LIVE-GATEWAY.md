# Private live OK AI gateway (lab only)

**NOT a public endpoint. Do not connect the floating widget, enable ingress,
deploy to Kubernetes, or expose through Cloudflare.** This prototype binds
only to `127.0.0.1:18082` and requires an operator-managed **separate** kagent
controller port-forward on `127.0.0.1:8083`.

The gateway performs independent, local, validated docs retrieval for each
question, submits the question to kagent via A2A JSON-RPC, validates the result
with the existing strict `answer_integrity` rules, and only sends a raw AI
answer if the validator accepts it.

## Steps

From `platform/ai/assistant`, first execute the tests:

```sh
python3 -m unittest discover -s tests -v
```

Ensure the vetted local index exists at
`/tmp/openkubes-docs-index.json`, and run the **private** controller
port-forward in one terminal:

```sh
kubectl --kubeconfig "$HOME/.kube/ok-kagent.yaml" \
  --context ok-kagent-admin@ok-kagent \
  -n kagent port-forward --address 127.0.0.1 \
  svc/kagent-controller 8083:8083
```

In a second terminal:

```sh
python3 -m public_beta.live_gateway --index /tmp/openkubes-docs-index.json
```

In a third terminal:

```sh
curl --silent --show-error --fail-with-body \
  -H 'Content-Type: application/json' \
  -d '{"question":"How do I install OpenKubes Local on macOS?"}' \
  http://127.0.0.1:18082/api/chat
```

The last command returns non-zero on HTTP 422 or 503. **A 422 rejection is
currently expected** based on prior private kagent answer quality tests. A
rejected response contains only `error` and a fixed safe fallback, not model
text or unsafe commands. A 503 indicates A2A transport/unavailability.
A successful 200 is explicitly labeled `lab_only: true` and
`provenance: independent_local_retrieval`.

## Release gates and limitations

- **No browser connectivity**. There is no authentication, TLS, rate limiting,
  origin enforcement, concurrency budget, public API contract, request audit
  policy or network exposure hardening.
- The independently retrieved local index may not match the deployed MCP tool
  results. Passing the validator here is **not proof** that the agent actually
  received the same sources, and is **not** a semantic or command-safety proof.
- For production, require attested same-request retrieval correlation, policy,
  rate limits, security/CVE clearance, source-grounded command QA and a
  deployment security review. The placeholder UI demo must stay offline.
- Never treat a returned source URL alone as proof that any accompanying
  factual prose is correct.
- Do not publish or send model prompts/responses to external logs. The lab
  gateway does not log request paths or question text.

**Public OK AI release status: HOLD.**
