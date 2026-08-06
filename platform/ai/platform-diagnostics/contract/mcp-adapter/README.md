# MCP adapter (agent-facing)

Exposes the three contract functions as MCP tools over **streamable-http** and
forwards each to the HTTP contract (the facade). Derived from the normative
`../openapi.yaml` Phase-1 contract. Holds **no Kubernetes credentials** — it
only talks to the facade; cluster access lives behind the contract in kagent's
read-only SA.

A consumer without an LLM (the `ok` CLI, OK-76) skips this and speaks HTTP directly.

## Tool mapping (1:1 with operationIds)

| MCP tool | facade endpoint |
|---|---|
| `get_platform_health` | `POST /v1/get_platform_health` |
| `investigate_workload` | `POST /v1/investigate_workload` |
| `collect_diagnostic_evidence` | `POST /v1/collect_diagnostic_evidence` |

The tool docstrings in `server.py` are the descriptions the agent uses to decide
when to call each — so the agent picks them **autonomously**, no system-prompt
steering needed (this is why MCP is cleaner than the Exec/CLI consumer).

## Build & deploy

```bash
docker buildx build --platform linux/amd64,linux/arm64 --provenance=false \
  -t ghcr.io/openkubes/platform-diagnostics-mcp-adapter:0.1.0 --push .
kubectl --kubeconfig ~/.kube/ok-ai.yaml apply -f deploy.yaml
```

Endpoint: `http://platform-diagnostics-mcp.platform-diagnostics.svc.cluster.local:8080/mcp`

## Register in OpenClaw (the first MCP consumer)

OpenClaw supports MCP natively (`openclaw mcp add`, HTTP transport). Diagnoses take
30-120s (LLM + read-only tool calls behind the contract), so set generous timeouts:

```bash
kubectl -n openclaw exec deploy/openclaw -- node dist/index.js mcp add platform-diagnostics \
  --url http://platform-diagnostics-mcp.platform-diagnostics.svc.cluster.local:8080/mcp \
  --transport streamable-http --timeout 300 --connect-timeout 10 \
  --include 'get_platform_health,investigate_workload,collect_diagnostic_evidence'
```

`mcp add` probes + saves to the pod's live `mcp.servers` config (enough to test in
this pod session). **For persistence** across pod restarts (the state dir is an
emptyDir), the resulting `mcp.servers` block must be baked into the shipped
`openclaw.json` (the openclaw chart configmap) — capture it with
`node dist/index.js mcp show` and add it to the config. OpenClaw stays
credential-less; RBAC remains `rbac.create=false`.
