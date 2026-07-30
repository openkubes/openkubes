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

ADR-021 selects **HTTP + OpenAPI** as the normative transport. The included
`contract/openapi.yaml` is still a **Draft implementation scaffold**; normative
finalization remains in OK-89/OK-90. It supplies three *named* functions and the
ADR-021-derived result shape (`RankedHypothesis.counter_evidence_status`,
`EvidenceRef` references-only, `provider_capabilities`) needed to exercise
Profile A. kagent speaks its own agent/A2A protocol and (per the OK-14
evaluation) does not natively expose these three functions with this schema. The
`facade/` is the thin shim that makes kagent a conformant **provider** without
leaking kagent specifics to consumers — that is exactly what keeps the backend
swappable (test 4).

If OK-14 concludes kagent *does* expose a directly conformant endpoint, the facade
collapses to a pass-through; the contract and consumers do not change either way.

## Files

| File | Purpose |
|---|---|
| `modelconfig.yaml` | kagent `ModelConfig` — shared Ollama (`gpt-oss:20b`). Host is a Provider Value (ok-cluster). |
| `agents/openkubes-platform-agent.yaml` | the single fronting `Agent`; lists specialists as delegates |
| `agents/specialists/*.yaml` | specialist `Agent`s, one Skill-Contract domain each |
| `tools/scoped-tools-server.yaml` | scoped kagent tools server (read-only SA) + its `RemoteMCPServer` — the read-only enforcement point |
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

### Read-only enforcement: the scoped tools server (decision 2026-07-24)

kagent's shipped tools are served by the **shared `kagent-tool-server`, which runs
under kagent's write-capable RBAC** (its `k8s-agent` can create/patch/delete/apply).
Referencing it would make read-only only *soft* (tool selection + prompt) and would
NOT satisfy ADR-021 test 2 (RBAC audit of the executing identity).

Decision (OK-92): enforce read-only via RBAC. `scoped-tools-server.yaml` runs a
**private copy of the tools server under the read-only SA `openkubes-platform-agent`**
and registers it as `RemoteMCPServer platform-diagnostics-tools` (same namespace).
Specialists reference that and are given only read tool names
(`k8s_get_resources`, `k8s_describe_resource`, `k8s_get_events`, `k8s_get_pod_logs`,
`k8s_get_resource_yaml`, `k8s_get_cluster_configuration`, `k8s_check_service_connectivity`).
Even if a write tool were exposed, the SA denies it — read-only is hard-enforced.

**Deploy-time `__FILL__`:** the tools image, port, args and the RemoteMCPServer
transport/URL must be copied from the shipped server (do not guess):

```bash
kubectl -n kagent get remotemcpserver kagent-tool-server -o yaml
kubectl -n kagent get deploy,svc -o wide
```

Fill `scoped-tools-server.yaml`, then uncomment it in `kustomization.yaml`. Until
then the specialists stay `ACCEPTED:False` (they reference the not-yet-created
RemoteMCPServer) — expected; the front agent is unaffected.

## Guardrails (stop rule, guideline Part C)

Read-only only (`get`/`list`/`watch`, secrets never). kagent ships its own default
RBAC and a default `k8s-agent` — those are **not** hardened to our guideline;
Profile A replaces them with the scoped SA in `rbac.yaml`. Do not expose this agent
as a second selectable model in Open WebUI — it is a provider behind the contract,
not a competing chat backend.
