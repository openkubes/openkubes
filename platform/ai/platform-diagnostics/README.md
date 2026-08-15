# Platform Diagnostics — Read-Only Contract + Implementation Profiles

Implements **ADR-Platform-021 (Read-Only Platform Diagnostics Contract)**,
which extends **ADR-Platform-015 (Agentic AI)**.

The asset here is a **contract**, not a component: a narrow, provider-neutral,
read-only interface through which any consumer requests platform diagnostics.
Agent runtimes (the *providers*) and frontends (the *consumers*) are
interchangeable behind/in front of it — that replaceability is the whole point
(ADR-021, "backend-swap test").

```
 Consumers                        Contract                     Providers
 ─────────                        ────────                     ─────────
 OpenClaw (conversational)  ┐                            ┌ Profile A: kagent
 ok CLI (OK-76)             ├─►  HTTP + OpenAPI  ◄────────┤ Profile B: deterministic stub
 Slack / incident tooling   ┘   (+ MCP adapter)          └   (backend-swap proof)
                                     │
                                     ▼  the three public functions
                get_platform_health · investigate_workload · collect_diagnostic_evidence
```

Consumers hold **no Kubernetes credentials**. They call the contract endpoint
only. Providers enforce Kubernetes RBAC inside the cluster; Phase-1 provider
identities are verifiably read-only (`get`/`list`/`watch`) — that is a contract
test, not a convention.

## Layout

```
platform/ai/platform-diagnostics/
├── consumer/
│   └── openclaw/             # first consumer, MCP-only and credential-less  ← OK-94
├── contract/
│   ├── openapi.yaml           # normative Phase-1 HTTP contract (v1.1.0)
│   ├── mcp-adapter/           # generated agent-facing adapter, DERIVED from openapi.yaml (OK-93)
│   └── tests/                 # executable provider-neutral ADR-021 tests 1–6
└── profiles/
    ├── stub/                  # Profile B — deterministic backend-swap proof ← OK-91
    └── kagent/                # Profile A (first) — kagent operations engine ← OK-92
        ├── modelconfig.yaml           # kagent ModelConfig: shared Ollama
        ├── agents/
        │   ├── openkubes-platform-agent.yaml   # single agent that fronts the contract
        │   └── specialists/                    # internal delegation targets (invisible to consumers)
        ├── tools/                     # kagent Tools = read-only Skill Contract implementations
        ├── rbac.yaml                  # read-only ClusterRole (get/list/watch, secrets EXCLUDED)
        ├── facade/                    # HTTP shim: OpenAPI function → kagent invocation → ADR-021 schema
        ├── charts/                    # Helm chart bundling CRDs + facade + RBAC
        └── README.md
```

## Ownership / ticket split

| Piece | Ticket | Repo |
|---|---|---|
| `contract/openapi.yaml` | **OK-90** (normative finalization) | `openkubes` (this repo) |
| `contract/tests/` + Profile B stub | **OK-91** (executable provider-neutral conformance suite) | `openkubes` (this repo) |
| `contract/mcp-adapter/` | **OK-93** (adapter derived from the accepted OpenAPI) | `openkubes` (this repo) |
| `profiles/kagent/` (Profile A implementation) | **OK-92** (integrate kagent as first provider profile) | `openkubes` (generic) + `ok-cluster` (provider values) |
| OpenClaw as first **consumer** (diagnostics skill via MCP adapter) | **OK-94** | `openkubes` + `ok-cluster` |

`contract/openapi.yaml` is the **normative, machine-readable Phase-1 contract**.
It defines the three public operations and their input, output, evidence,
capability, and error schemas. Provider profiles and the optional MCP adapter
derive from it; provider endpoints and credentials remain Provider Values.

## Executable contract suite

The same HTTP-level test suite runs against any provider. By default it starts
Profile B on an ephemeral loopback port:

```bash
make verify
```

Set `DIAGNOSTICS_BASE_URL` and `DIAGNOSTICS_RBAC_PATH` to run it unchanged
against a deployed provider. The six tests cover schema conformance, RBAC,
evidence hygiene, backend swap, capability deltas, and counter-evidence.

## What lives where (generic vs. provider values)

Same convention as `platform/ai/openclaw`: reusable component here in
`openkubes`; concrete, cluster-specific values (real Ollama endpoint, model,
cluster refs, credentials, Claims) in the private `ok-cluster` repo under
`ok-cluster/kagent/`.

## Stop rule (guideline Part C) — reminder for this component

Read-only stays read-only: `get`/`list`/`watch` only, **secrets never** in any
RBAC rule. `propose_remediation` (Phase 2) is still non-executing;
`execute_approved_remediation` needs its **own ADR**. Running kagent *also* as a
second selectable model in Open WebUI (a parallel frontend backend) trips the
stop rule — here kagent is a **provider behind the contract**, not a competing
chat backend.

## References

- [ADR-Platform-021 — Read-Only Platform Diagnostics Contract](../../../architecture/decisions/ADR-Platform-021-read-only-platform-diagnostics-contract.md)
- [ADR-Platform-015 — Agentic AI](../../../architecture/decisions/ADR-Platform-015-agentic-ai.md)
- [Implementation guideline](../../../docs/agentic-ai-poc-guideline.md)
- [Problem statement](../../../docs/problem-statement-platform-diagnostics-contract.md)
- [OK-89](https://kubernauts.atlassian.net/browse/OK-89) · [OK-90](https://kubernauts.atlassian.net/browse/OK-90) · [OK-91](https://kubernauts.atlassian.net/browse/OK-91) · [OK-92](https://kubernauts.atlassian.net/browse/OK-92) · [OK-93](https://kubernauts.atlassian.net/browse/OK-93) · [OK-94](https://kubernauts.atlassian.net/browse/OK-94)
