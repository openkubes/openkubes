# MCP adapter (agent-facing)

Exposes the three contract functions as MCP tools over **streamable-http** and
forwards each call to the HTTP provider. It is derived from the normative
`../openapi.yaml` Phase-1 contract and holds **no Kubernetes credentials** —
cluster access remains behind the contract in the selected provider profile.

The MCP surface is generated from `../openapi.yaml`; tool names, descriptions,
request parameters, defaults, and HTTP paths are not declared independently in
`server.py`. This preserves the required direction of ownership:

```text
OpenAPI contract -> generated_contract.py -> MCP tools -> HTTP provider
```

`generated_contract.py` is committed so the runtime image needs no generator or
OpenAPI parser. The generation check fails whenever the OpenAPI source changes
without a corresponding adapter update.

A consumer without an LLM (the `ok` CLI, OK-76) skips this and speaks HTTP directly.

## Tool mapping (1:1 with operationIds)

| MCP tool | HTTP endpoint |
|---|---|
| `get_platform_health` | `POST /v1/get_platform_health` |
| `investigate_workload` | `POST /v1/investigate_workload` |
| `collect_diagnostic_evidence` | `POST /v1/collect_diagnostic_evidence` |

Descriptions exposed to the agent come from the OpenAPI operation summaries and
descriptions. The adapter therefore cannot silently redefine contract semantics.

## Generate and verify

```bash
make generate  # intentionally update generated_contract.py from openapi.yaml
make verify    # drift check, unit/runtime tests, and Python syntax validation
```

The verification environment requires Python 3.10 or newer (the image uses
Python 3.12). If the system `python3` is older, pass an explicit interpreter:

```bash
make verify PYTHON=/path/to/python3.12
```

The generated mapping includes every OpenAPI operation with an `operationId`.
Only JSON `POST` operations are accepted because ADR-021 Phase 1 exposes
read-only diagnostic requests and no mutation path.

## Build & deploy

```bash
docker buildx build --platform linux/amd64,linux/arm64 --provenance=false \
  -t ghcr.io/openkubes/platform-diagnostics-mcp-adapter:0.2.0 --push .
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
