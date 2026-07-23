# MCP adapter (optional, agent-facing)

A **thin** adapter that exposes the three contract functions as MCP tools, so an
LLM consumer (OpenClaw today) can call them via tool-calling. It is **derived
from `../openapi.yaml`** — the OpenAPI stays normative; the MCP tool names and
argument schemas are generated from it, never hand-authored in parallel (ADR-021:
"the schema MUST NOT exist only as MCP tool descriptions").

A consumer without an LLM (the `ok` CLI, OK-76; classical automation) skips this
entirely and speaks HTTP/OpenAPI directly.

## Tool mapping (generated 1:1 from operationIds)

| MCP tool | HTTP operation | Purpose |
|---|---|---|
| `get_platform_health` | `POST /v1/get_platform_health` | cross-cluster health snapshot |
| `investigate_workload` | `POST /v1/investigate_workload` | diagnostic report for one workload |
| `collect_diagnostic_evidence` | `POST /v1/collect_diagnostic_evidence` | evidence bundle (refs only) |

## Generation (recommended)

Do not hand-write this server. Generate it from the spec, e.g. an
`openapi-mcp`-style bridge that reads `../openapi.yaml` and serves the operations
as MCP tools. Pin the generator and check in the lockfile; regenerate on any
`openapi.yaml` change. The adapter is stateless and holds only the contract
endpoint URL + a bearer token to the provider — **no Kubernetes credentials**
(consumers never get cluster access; ADR-021 Authorization model).

## Consumer wiring (OpenClaw)

OpenClaw declares a single **Platform Diagnostics Skill Contract** whose
implementation is this MCP adapter's endpoint. See
`ok-cluster/openclaw` for the concrete, per-instance wiring (endpoint + token).
