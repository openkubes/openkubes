# Profile A — kagent operations engine (OK-92)

The **first** implementation profile of the Read-Only Platform Diagnostics
Contract (ADR-021). A single **`openkubes-platform-agent`** fronts the contract
and delegates internally to specialist agents (Kubernetes, Cilium, observability,
Helm, Argo). **Internal delegation is invisible to consumers** — they see only
the three contract functions.

```
  contract (HTTP/OpenAPI + MCP adapter)
            │
            ▼
      facade/  ──────────────────► openkubes-platform-agent (kagent Agent)
  (maps the 3 functions to             │  delegates (A2A), invisible to consumers
   an agent invocation and             ├─► kubernetes-agent
   shapes the ADR-021 schema)          ├─► cilium-agent
                                       ├─► observability-agent
                                       ├─► helm-agent      (declared)
                                       └─► argo-agent       (declared)
            │
            ▼
      Kubernetes API — ServiceAccount `openkubes-platform-agent`
      read-only: get/list/watch, secrets EXCLUDED  (rbac.yaml, contract test 2)
```

## Why a facade in front of kagent

ADR-021's normative transport is **HTTP + OpenAPI**, with three *named* functions
and a strict result schema (`RankedHypothesis.counter_evidence_status`,
`EvidenceRef` references-only, `provider_capabilities`). kagent speaks its own
agent/A2A protocol and (per the OK-14 evaluation) does not natively expose these
three functions with this schema. The `facade/` is the thin shim that makes
kagent a conformant **provider** of the contract without leaking kagent specifics
to consumers — that is exactly what keeps the backend swappable (test 4).

If OK-14 concludes kagent *does* expose a directly conformant endpoint, the facade
collapses to a pass-through; the contract and consumers do not change either way.

## Files

| File | Purpose |
|---|---|
| `modelconfig.yaml` | kagent `ModelConfig` — shared Ollama (`gpt-oss:20b`). Host is a Provider Value (ok-cluster). |
| `agents/openkubes-platform-agent.yaml` | the single fronting `Agent`; lists specialists as delegates |
| `agents/specialists/*.yaml` | specialist `Agent`s, one Skill-Contract domain each |
| `tools/cluster-inspection-toolserver.yaml` | read-only Cluster Inspection tools (kagent `ToolServer`) |
| `rbac.yaml` | `ServiceAccount` + read-only `ClusterRole` + binding (get/list/watch, no secrets) |
| `facade/` | OpenAPI→kagent shim (skeleton), `Dockerfile`, chart values |
| `charts/platform-diagnostics-kagent/` | Helm chart: facade Deployment/Service + RBAC |
| `kustomization.yaml` | applies the kagent CRs (ModelConfig, Agents, Tools) as one unit |

## kagent CRD shapes — confirmed against the installed version

The CRs target the schemas installed by `ok-cluster/kagent/Makefile`
(`KAGENT_VERSION=0.9.9`), verified via `kubectl explain` on ok-ai:

- **`ModelConfig` — `kagent.dev/v1alpha2`**: `spec.provider`, `spec.model`,
  `spec.ollama.host`, `spec.ollama.options` (string map, holds `num_ctx`).
- **`Agent` — `kagent.dev/v1alpha2`**: `spec.type: Declarative` + `spec.declarative`
  wrapper; `modelConfig` (name), `systemMessage`, `tools[]`, and `a2aConfig`
  (instantiates the A2A server the facade calls). Sub-agents are attached as
  `tools[].agent` typed refs; MCP tools as `tools[].mcpServer` (`name` + `toolNames`).
- **`ToolServer` — `kagent.dev/v1alpha1`**: `spec.description` + `spec.config.stdio`
  (`command` required, `args`, `readTimeoutSeconds`).

Two things still need confirming **at deploy time** (they depend on runtime state,
not the schema):

1. `toolNames` on `cluster-inspection` must match the tools the ToolServer actually
   advertises — check `kubectl get toolserver cluster-inspection -o yaml` (status)
   after it starts. Or reference kagent's built-in k8s tools instead (see the
   ToolServer file's note and the shipped `k8s-agent`).
2. How kagent schedules the ToolServer's stdio process and which ServiceAccount it
   runs as — the read-only SA (`rbac.yaml`) must be the identity behind the kubectl
   calls. Pin it via the kagent values.

## Guardrails (stop rule, guideline Part C)

Read-only only (`get`/`list`/`watch`, secrets never). kagent ships its own default
RBAC and a default `k8s-agent` — those are **not** hardened to our guideline;
Profile A replaces them with the scoped SA in `rbac.yaml`. Do not expose this agent
as a second selectable model in Open WebUI — it is a provider behind the contract,
not a competing chat backend.
