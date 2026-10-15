# OK AI Public Beta — A2A API discovery (read-only)

**Scope:** safe first step after OK-202. This does **not** deploy a public gateway, invoke an LLM, or change the website.

## Prerequisites

- Authorized access to the **isolated `ok-kagent` test cluster**.
- Verify the active kubeconfig/context before opening a port-forward.
- `kagent-controller` Service in namespace `kagent`; confirm its port 8083 locally.

In terminal 1:

```sh
kubectl --kubeconfig "$HOME/.kube/ok-kagent.yaml" --context ok-kagent-admin@ok-kagent \
  -n kagent port-forward --address 127.0.0.1 svc/kagent-controller 8083:8083
```

In terminal 2:

```sh
python3 platform/ai/assistant/public_beta/a2a_preflight.py
```

This **GET-only** discovery checks the documented kagent A2A agent card route:
`/api/a2a/openkubes-assistant/openkubes-docs-agent/.well-known/agent-card.json`.
**Observed on the 2026-10-15 lab installation (kagent controller 0.9.12):** `/.well-known/agent.json` returned HTTP 200 with JSON-RPC error `-32600 invalid request`; `/.well-known/agent-card.json` returned HTTP 200 and Agent Card `name=openkubes_docs_agent`, `capabilities.streaming=true`. Kubernetes Agent status was `Ready=True`, `Accepted=True`. These were operator-observed results, not a test executed by this PR.\n\nThe code connects only to `127.0.0.1`, refuses HTTP redirects, bounds the response to 64 KiB, and prints minimal, nonsecret metadata. A valid card **does not prove** agent invocation, model access, secure networking or citation integrity.

## Next release gate (NOT accomplished by this PR)

1. Record **installed** kagent controller version and verify the correct A2A task request/response/stream protocol against it. Keep any task invocation private in lab; do not assume all versions match.
2. Decide gateway placement and how it authenticates to the private A2A interface. **Never expose the controller or MCP/Ollama directly.**
3. Add gateway-side request size limits, quotas, concurrency caps, timeouts, CORS/origin handling, abuse protection and telemetry redaction.
4. Bind citations to trusted retrieval IDs/URLs, not LLM-authored links alone; verify every executable installation command against sources.
5. Remediate/triage container findings, prove Kubernetes NetworkPolicy boundaries, and get explicit production security approval; the OK-202 lab exception is not public release approval.
6. Add a preview-only MkDocs widget, run manual positive/negative/prompt-injection/load checks and use the existing preview-first website release.
7. Post-beta: add automated E2E and regression tests, per release scope.

References:
- [OK-202 validation](../POC-VALIDATION.md)
- [Security assessment](../SECURITY-ASSESSMENT.md)
- [kagent A2A documentation](https://kagent.dev/docs/kagent/0.x/examples/a2a-agents/)


## Operator-observed A2A invocation (2026-10-15)

Using the same localhost port-forward and installed kagent 0.9.12/A2A protocol 0.3, a private JSON-RPC `message/send` request with `configuration.blocking=true` and the question "How do I install OpenKubes Local on macOS?" returned `result.kind=task`, `result.status.state=completed`, and a generated installation answer. **This proves invocation/response only, not correct citations, tool-call tracing or safe public access.**

Manual comparison against [ok-local/docs/tutorial-basic.md](https://github.com/openkubes/ok-local/blob/main/docs/tutorial-basic.md) revealed release-blocking answer integrity defects:
- The source specifies Ubuntu **24.04** with **4 CPUs, 8G memory, 40G disk and cloud-init**; the answer instead presented Ubuntu **22.04**, **2G memory**, **20G disk**, without that cloud-init setup.
- The source installs a Linux `virtctl` binary **inside the Ubuntu VM** via SSH; the answer instructed installation of a Linux binary on the macOS host.
- The reply used unlinked `source_id` tokens instead of clickable revision-pinned GitHub URLs and generated malformed command-in-table Markdown, contrary to the checked-in system prompt.

**Gate: HOLD** on public launch. Next action is private, repeatable command/citation integrity tests against trusted MCP retrieval output, not a production exposure. Do not treat `completed` as equivalent to grounded/correct.
