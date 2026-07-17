# ADR-Platform-021: Read-Only Platform Diagnostics Contract

**Status:** Draft, revision 3 — three-way review resolutions of 2026-07-17 incorporated; Go for Jira issued
**Extends:** ADR-Platform-015 (Agentic AI)
**Related:** OK-14 (evaluation), OK-76 (`ok` CLI — future consumer)
**Deciders:** Arash / Claude / GPT (three-way review), implementation: Daniel
**Date:** 2026-07-17

## Context

Manual incident diagnostics do not scale across clusters and operators (see Problem Statement). OK-14 evaluated agent runtimes; direct frontend→runtime coupling fails the backend-swap test. Per the platform chain — Capability → Contract → Implementation Profile → Provider Values → Contract Tests — the boundary must be an OpenKubes-owned contract.

## Decision

OpenKubes defines a read-only **Platform Diagnostics Contract**: a narrow, provider-neutral interface through which any consumer requests platform diagnostics. Agent runtimes and frontends are interchangeable behind/in front of this contract.

### Capability

Standardized platform diagnostics for OpenKubes clusters — LLM-assisted or runbook-driven.

### Contract (Phase 1 — read-only, three public functions)

| Function | Purpose | Forcing consumer |
|---|---|---|
| `get_platform_health` | Cross-cluster/platform health snapshot | Incident diagnostic workflow |
| `investigate_workload` | Standardized diagnostic report for one workload | Incident diagnostic workflow |
| `collect_diagnostic_evidence` | Raw evidence bundle without hypothesis generation | Incident handoff, audit, offline expert review |

`collect_diagnostic_evidence` is public because it supports incident handoff, audit, and offline expert review **without requiring hypothesis generation** — it is a consumer-forced capability, not a technical decomposition of the provider.

**Declined for Phase 1:** `analyze_cluster_issue` (`issue: string`) — a free-form prompt interface is hard to make schema-stable, hard to test, and strongly provider-dependent; it would be the weakest part of the contract. A future, structured `investigate_cluster_condition` (cluster, time_range, enumerated signals such as node_not_ready, api_latency, workload_failures, network_degradation) may be added when a consumer forces it.

### Normative schema (excerpt)

```yaml
investigate_workload:
  input:
    cluster: string          # logical cluster name, not endpoint
    namespace: string
    workload: string
    time_range: duration
  output:
    summary: string
    symptoms: []string
    evidence: []EvidenceRef
    probable_causes: []RankedHypothesis
    recommended_next_steps: []string   # human actions; never executed
    references: []string               # runbooks, ADRs, dashboards

RankedHypothesis:
  hypothesis: string
  confidence: low | medium | high
  evidence_refs: []string
  contradicting_evidence_refs: []string
  counter_evidence_status: found | none_found | not_checked
  # Distinguishes: counter-evidence was sought and found / sought and not
  # found / never sought. A hypothesis without sought counter-evidence is a guess.

EvidenceRef:
  type: string
  source: string
  status: available | unavailable | partial
  reason: string                          # mandatory when not "available"
  uri: string                             # reference, never embedded payloads/secrets
  collected_at: timestamp
```

### Transport

- **Normative service contract: HTTP + OpenAPI**, owned in `openkubes/openkubes`. Framework-neutral; usable by CLI, controllers, portals, tests, and classical automation.
- **MCP: optional agent-facing adapter** (thin mapping derived from the OpenAPI contract). A consumer without an LLM needs no MCP.
- The contract schema MUST NOT exist only as MCP tool descriptions — otherwise the semantic contract de facto belongs to the agent ecosystem.

### Provider capability declaration

Talos vs. RKE2 (and any future OS/distribution differences) are a **provider capability delta, never a contract delta**. Providers declare:

```yaml
provider_capabilities:
  workload_events: true
  workload_logs: true
  cilium_diagnostics: true
  host_journal: false      # e.g. Talos
  node_shell: false        # e.g. Talos
```

Consumers receive the identical API contract everywhere; unavailable evidence is reported explicitly via `EvidenceRef.status: unavailable` with a reason (e.g. "node shell access is not part of this provider profile") — never by silently returning less data.

### Explicitly out of scope (Phase 1)

- `propose_remediation` — declared Phase 2 option, still non-executing (the contract remains read-only in effect; "Read-Only" in the title survives Phase 2).
- `execute_approved_remediation` — **separate ADR required** (per ADR-015), with human approval, RBAC, audit trail, policy enforcement, rollback, blast-radius limits, and four-eyes principle for PROD. Deliberately NOT listed as a peer method in this contract.

### Authorization model

- Consumers hold no Kubernetes credentials. They call the contract endpoint only.
- Providers enforce Kubernetes RBAC per cluster / namespace / agent / tool inside the cluster.
- Phase 1 provider service accounts are verifiably read-only (get/list/watch); this is a contract test.

### Audit and data separation

Four artifacts with **distinct retention and access policies**:

1. **Invocation audit** — who called which contract function when (central, long retention).
2. **Provider tool trace** — which internal tools/agents the provider used (provider-local).
3. **Diagnostic result** — what was returned to the consumer.
4. **Raw evidence** — logs, events, metrics remain at their sources; the contract carries references.

The central audit log must never contain raw log payloads or secrets.

## Implementation Profiles

<!-- Components appear ONLY here and in Rationale. -->

**Profile A (first): kagent operations engine.** A single `openkubes-platform-agent` fronts the contract; it may delegate internally to specialist agents (Kubernetes, Cilium, observability, Helm, Argo). Internal delegation is invisible to consumers. Real provider values (manifests, endpoints, credentials) live in `ok-cluster` (private).

**Profile B (declared, not built):** any other agent runtime, or a classical runbook/API implementation with no LLM at all. Existence of Profile B is the backend-swap test.

## Consumers

**First consumer:** conversational assistant (OpenClaw) — presents diagnostics, composes with Jira/GitHub/docs workflows. Restricted call to the contract (via MCP adapter) only; no cluster access.
**Second consumer (forcing `collect_diagnostic_evidence`):** incident handoff / audit / offline expert review.
**Declared future consumers:** `ok` CLI (OK-76), Slack workflows, incident tooling, future OpenKubes controllers.

## Contract Tests

1. OpenAPI schema conformance of all three functions against any provider, with zero references to a specific runtime or frontend.
2. RBAC audit: Phase 1 provider identity has no verbs beyond get/list/watch.
3. Evidence output contains references, never embedded secrets/credentials or raw payloads.
4. Backend-swap: consumer test suite passes unchanged against a stub Profile B.
5. Capability delta: a provider that declares a capability as absent MUST return `status: unavailable` with reason for affected evidence — silent omission is a test failure.
6. Every `RankedHypothesis` carries `confidence`, `contradicting_evidence_refs`, and `counter_evidence_status`. `not_checked` is a test failure for finalized diagnostic results.

## Consequences

**Positive:** frontends and agent runtimes become replaceable; diagnostics standardized across clusters and operators; write path structurally impossible in Phase 1; identical contract across Talos and RKE2; potential platform differentiator (friendly assistant outside, RBAC-controlled agents inside).

**Negative / costs:** contract maintenance in the mother repo; OpenAPI + MCP adapter as one more indirection layer; risk of the contract lagging behind provider capabilities.

**Accepted Risks:** AR-1 (prompt injection — re-assessed: read-only scope bounds impact to information disclosure; evidence-ref rule and audit separation mitigate), AR-2 (GPU budget — provider-side inference on ok-gpu must respect existing limits).

## What we are NOT deciding

- Which agent framework OpenKubes "adopts" — none; the contract owns the boundary.
- Duplicate runbooks in frontend and runtime — runbooks live behind the contract.
- Any parallel/autonomous remediation by any component.

## Rationale (summary)

Direct coupling `frontend skill → runtime-specific API → runtime` binds OpenKubes to provider values and fails the backend-swap test ("a hard-wired coupling never survives a backend swap unnoticed → contract, not provider value"). A narrow HTTP/OpenAPI contract in the mother repo makes the conversational assistant merely the first consumer and the agent runtime merely the first provider — complementary instead of redundant. The title avoids "Agent" and "AI-Assisted" because the decision is broader than either: the asset is the diagnostics interface.

## Review resolutions (2026-07-17)

| Question | Resolution |
|---|---|
| Three or four functions | Three; `analyze_cluster_issue` declined (free-form prompt interface) |
| `collect_diagnostic_evidence` public | Yes — forcing consumer: incident handoff / audit / offline review |
| Transport | HTTP + OpenAPI normative; MCP as thin optional adapter |
| Talos/RKE2 | Provider capability delta, never a contract delta |
| Title | Read-Only Platform Diagnostics Contract |
| Counter-evidence semantics | `counter_evidence_status: found / none_found / not_checked`; `not_checked` fails finalized results |
