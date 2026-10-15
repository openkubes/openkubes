# Private kagent A2A integrity probe

**Local manual lab test only — no public gateway or browser connection.**

This probe makes one A2A JSON-RPC `message/send` call through an operator-established `kubectl port-forward` bound to **127.0.0.1**, checks the completed task's text artifacts and reports an integrity verdict against **independent, local, same-question** docs retrieval. It never treats a completed A2A task as proof of a correct answer.

## 1. Tests and index

From `platform/ai/assistant`:

```sh
python3 -m unittest discover -s tests -v
python3 indexer.py build --output /tmp/openkubes-docs-index.json
```

## 2. Start port-forward in a separate terminal

```sh
kubectl --kubeconfig "$HOME/.kube/ok-kagent.yaml" \
  --context ok-kagent-admin@ok-kagent \
  -n kagent port-forward --address 127.0.0.1 \
  svc/kagent-controller 8083:8083
```

Keep this terminal open and verify the selected context is the isolated **ok-kagent** lab. Do not configure an ingress or expose port 8083 externally.

## 3. Run one private probe

```sh
python3 -m public_beta.private_a2a_probe \
  --index /tmp/openkubes-docs-index.json
```

The probe prints **only** verdict, reason codes, response length, source IDs and a privacy-safe `diagnostics` object of fixed numeric/boolean fields. Diagnostic counters distinguish recognized shell fences, unsupported markup, exact-match command blocks, clickable trusted links and bare source tokens. Neither command text nor the full answer is printed. The `retrieval_at_limit` boolean means only that eight chunks were returned, **not** that the documentation is complete. It does not print private model responses or the full context. Exit code: `0` accepted, `1` rejected/no sources, `2` invocation/parsing error.

Expected at this stage: a **rejection may be the correct outcome** if the model outputs unlinked `source_id` tokens, inline commands, unsupported Markdown or commands not copied verbatim from retrieved content. Do **not** loosen the validator to force PASS. Diagnose the evidence gap first.

## Boundaries

- The local index may differ from the **deployed MCP index**. This is a conservative comparison, not an attestation of what the remote agent retrieved.
- The A2A response format is expected to be JSON-RPC 2.0, task completed, with textual artifact parts; asynchronous/noncompleted tasks are rejected.
- The probe can establish that a locally checked answer meets the **syntactic** validator contract. It cannot validate all factual prose or guarantee command safety.
- Requests flow to the existing private cluster via the explicit port-forward. No Kubernetes mutations, gateway deployment, frontend wiring or public exposure.
- Do not paste full agent text if it includes unrelated internal details. Review any log carefully before sharing.

**Public Beta release gate remains HOLD**, including gateway isolation, quotas, same-request source binding, operational policy and outstanding CVE review.
