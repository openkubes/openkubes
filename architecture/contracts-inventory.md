# OpenKubes Contracts Inventory

> Derived projection of the ADR series and README — the ADRs remain the source of truth.
> Per ADR-Platform-022, capability contracts are framework artifacts and live in `openkubes/openkubes`; the `ok-*` repositories are v1 reference implementations.

Chain: **Capability → Contract → Implementation Profile → Provider Values → Contract Tests**

## Core Capability Contracts

| Contract | Defined in | Repo / v1 Reference Implementation | Status |
|---|---|---|---|
| Cluster Lifecycle Contract | ADR-Platform-004, ADR-Platform-008 | `ok-cluster` | ✅ v0.10.0 |
| Workload Cluster Registration Contract | ADR-Platform-013 | Make target (replaceable — the naming contract, not the tooling, is normative) | ✅ |
| OS Capability Contract | ADR-Platform-016 | `ok-linux` (Talos) | ✅ v0.1.1 |
| Persistent Storage Contract | ADR-Platform-009 | `ok-storage` (Longhorn, three storage classes) | ✅ v0.1.0 |
| Ingress Contract | ADR-Platform-010 | Traefik, ingress class `ok-ingress` | ✅ |
| Observability Capability Contract | ADR-Platform-018 | `ok-observability` | 🚧 scaffold |
| GitOps Contract | ADR-Platform-011 | `ok-gitops` (ArgoCD) | 📋 planned |
| Secret Contract | ADR-Platform-011 | open — Vault, Infisical, or cloud secrets manager (the contract, not the product, is the capability) | 📋 planned |
| Shared Platform Services Contract | ADR-Platform-020 | `ok-shared` | Accepted — implementation awaits additional forcing consumers |
| Read-Only Platform Diagnostics Contract | ADR-Platform-021 | HTTP + OpenAPI (normative); MCP as optional agent-facing adapter | Phase 1 |
| Application Contract | — (no ADR yet) | `ok-apps` | 📋 planned |

## Agentic AI Contracts (ADR-Platform-015)

| Contract | Role |
|---|---|
| Agent Interface Contract v1 | Versioned API between frontend (Open WebUI) and agent backend (OpenClaw, replaceable) |
| Cluster Inspection Contract | Skill Contract (read-only) — kubectl (read-only), kagent tool, MCP server |
| Log Query Contract | Skill Contract (read-only) — OpenSearch client, MCP server |
| Knowledge Graph Contract | Skill Contract (read-only) — okgraph query interface |
| Documentation Contract | Skill Contract (read-only) — RAG over ADRs/guides |

## Announced, no ADR yet

- **Workload Cluster Lifecycle Contract** — named as a future ADR in ADR-Platform-013.
