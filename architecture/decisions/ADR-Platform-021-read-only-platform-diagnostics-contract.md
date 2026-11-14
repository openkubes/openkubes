# ADR-Platform-021: Read-Only Platform Diagnostics Contract

**Status:** Draft, revision 4 — **review-ready**. Revision 3 carried the three-way review resolutions of 2026-07-17. Revision 4 records the decisions that were taken at spec level while OK-90 was implemented (2026-08-06 … 2026-08-14) and that revision 3 did not yet describe. Pending final three-way sign-off; see *Open for the final review*.
**Extends:** ADR-Platform-015 (Agentic AI)
**Related:** OK-14 (evaluation), OK-76 (`ok` CLI — future consumer)
**Deciders:** Arash / Claude / GPT (three-way review), implementation: Daniel
**Date:** 2026-07-17 (revision 4: 2026-08-14)
**Normative artifact:** `platform/ai/platform-diagnostics/contract/openapi.yaml`, `info.version` **1.1.0**. Where this document and the OpenAPI file disagree, the OpenAPI file is normative and this document is a defect.

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

Aligned with `openapi.yaml` 1.1.0. Every successful response is **self-describing**: it names its subject, the time window actually evaluated, the time of generation, and the invocation it belongs to — because the forcing consumer is a result that leaves the HTTP exchange (incident ticket, audit record, offline review).

```yaml
investigate_workload:
  input:
    cluster: string          # logical cluster name, not endpoint
    namespace: string
    workload: string
    time_range: duration     # requested; the provider may clamp it
  output:
    invocation_id: InvocationId
    cluster: string
    namespace: string
    workload: string
    generated_at: timestamp
    effective_time_range: TimeWindow   # window actually evaluated
    summary: string
    symptoms: []string
    evidence: []EvidenceRef
    probable_causes: []FinalizedRankedHypothesis
    recommended_next_steps: []string   # human actions; never executed
    references: []string               # runbooks, ADRs, dashboards

TimeWindow:
  start: timestamp
  end: timestamp
  # A clamped time_range that is not reported back makes a result
  # irreproducible. Reporting the absolute window is what makes it auditable.

RankedHypothesis:
  hypothesis: string
  confidence: low | medium | high
  evidence_refs: []EvidenceId               # supporting evidence, by id
  contradicting_evidence_refs: []EvidenceId
  counter_evidence_status: found | none_found | not_checked
  # Distinguishes: counter-evidence was sought and found / sought and not
  # found / never sought. A hypothesis without sought counter-evidence is a guess.
  # FinalizedRankedHypothesis narrows the enum to found | none_found, so
  # not_checked is structurally impossible in a successful response.

EvidenceRef:
  id: EvidenceId          # always present, including when unavailable
  type: string
  source: string
  status: available | unavailable | partial
  reason: string          # mandatory when status is unavailable or partial
  uri: string             # mandatory when available or partial; reference only,
                          # never an embedded payload or secret
  collected_at: timestamp

EvidenceId:
  # Provider-assigned opaque identifier, unique within one invocation and
  # stable wherever that evidence is referenced across the invocation's audit
  # artifacts. Consumers compare it as an opaque string and derive nothing
  # from its shape.

ClusterHealth:
  cluster: string
  status: healthy | degraded | unavailable | unknown
  summary: string
  signals: []string
  provider_capabilities: ProviderCapabilities
```

Hypotheses reference evidence by **`EvidenceId`, not by `uri`**, because `uri` is legitimately absent when evidence is unavailable, and two evidence items of different `type` may share a `uri`. Referential integrity — every referenced id exists in the same response, ids unique within an invocation — is an executable contract test, not a convention.

### Provider health semantics

`ClusterHealth.status` distinguishes the state of the **cluster** from the state of the **provider's knowledge**. `unknown` means the provider could not determine a reliable health state; it **must not be coerced to `unavailable`**, which asserts that the cluster is not reachable. Coercing provider uncertainty into `unavailable` makes an incident report claim an outage where none was observed. Other clusters in the same response may still carry valid results.

### Contract versioning

The `/v1` path prefix is the **compatibility-major** API version. `info.version` versions this contract document within that major: backward-compatible additions may increment it, while an incompatible change to the public surface requires a new path major. Consumers pin the path major; conformance suites pin `info.version` so that a branch which falls behind cannot silently validate against an older contract.

### Transport

- **Normative service contract: HTTP + OpenAPI**, owned in `openkubes/openkubes`. Framework-neutral; usable by CLI, controllers, portals, tests, and classical automation.
- **MCP: optional agent-facing adapter** (thin mapping derived from the OpenAPI contract). A consumer without an LLM needs no MCP.
- The contract schema MUST NOT exist only as MCP tool descriptions — otherwise the semantic contract de facto belongs to the agent ecosystem.
- A provider implemented with a framework that generates its own OpenAPI document (e.g. FastAPI) has **two** schema sources. The generated document is not authoritative; it is diffed against the normative file by a contract test. Without that diff, provider drift is invisible.

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

- **Consumers authenticate with a consumer identity**, carried as a bearer token (`bearerAuth`, applied globally). That identity denotes the calling consumer — an assistant, a CLI, a controller, a test suite — and is **never a Kubernetes credential**. Issuer, audience, and claim mapping are provider profile values, not part of this contract.
- Consumers hold no Kubernetes credentials. They call the contract endpoint only.
- Providers enforce Kubernetes RBAC per cluster / namespace / agent / tool inside the cluster.
- Phase 1 provider service accounts are verifiably read-only (get/list/watch); this is a contract test.
- Declaring `401`/`403` without defining how a consumer authenticates would leave the authorization model untestable, which is why the scheme is part of the normative surface rather than a deployment detail.

### Audit and data separation

Four artifacts with **distinct retention and access policies**:

1. **Invocation audit** — which consumer identity called which contract function when (central, long retention).
2. **Provider tool trace** — which internal tools/agents the provider used (provider-local).
3. **Diagnostic result** — what was returned to the consumer.
4. **Raw evidence** — logs, events, metrics remain at their sources; the contract carries references.

The central audit log must never contain raw log payloads or secrets.

These four artifacts are only separable if they are also **joinable**. The contract therefore carries:

- **`invocation_id`** — provider-assigned, returned in every successful result body *and* in the `X-Invocation-Id` response header on **every** response including errors. An authorization failure or provider outage stays traceable although it carries no result. It is in the body as well as the header because a result that is exported into a ticket or an offline review loses its HTTP envelope.
- **`X-Request-Id`** — optional consumer-supplied correlation id, echoed into the invocation audit, so a consumer-side incident record and the platform audit trail can be joined from either end.
- **`EvidenceId`** — joins a diagnostic result to the raw evidence it rests on, without moving the evidence.

Neither id carries evidence content; both are safe to log centrally and to quote in a ticket.

## Implementation Profiles

<!-- Components appear ONLY here and in Rationale. -->

**Profile A (first): kagent operations engine.** A single `openkubes-platform-agent` fronts the contract; it may delegate internally to specialist agents (Kubernetes, Cilium, observability, Helm, Argo). Internal delegation is invisible to consumers. Real provider values (manifests, endpoints, credentials) live in `ok-cluster` (private).

**Profile B (conformance stub):** a deterministic classical HTTP implementation
with no LLM, agent runtime, or Kubernetes access. It lives under
`platform/ai/platform-diagnostics/profiles/stub` and exists solely to prove the
backend swap: the same consumer-facing suite runs unchanged against this stub or
any other provider.

## Consumers

**First consumer:** conversational assistant (OpenClaw) — presents diagnostics, composes with Jira/GitHub/docs workflows. Restricted call to the contract (via MCP adapter) only; no cluster access.
**Second consumer (forcing `collect_diagnostic_evidence`):** incident handoff / audit / offline expert review.
**Declared future consumers:** `ok` CLI (OK-76), Slack workflows, incident tooling, future OpenKubes controllers.

## Contract Tests

The suite is executable and provider-neutral (`platform/ai/platform-diagnostics/contract/tests`). It pins `info.version` of the normative contract; a suite that resolves the contract relative to its own branch can pass against a stale copy, which has happened and is therefore a test requirement, not advice.

1. **Schema conformance and provider neutrality** — all three functions validate against the normative OpenAPI, with zero references to a specific runtime or frontend in the public surface. For a provider whose framework generates its own OpenAPI document, that generated document is diffed against the normative file.
2. **RBAC audit** — the Phase-1 provider identity has no verbs beyond get/list/watch and no access to secrets.
3. **Evidence hygiene** — output contains references, never embedded secrets, credentials, or raw payloads.
4. **Backend swap** — the same consumer suite runs unchanged against **at least two independent providers in one run** (Profile B stub and Profile A), and their results are provably not the same artifact. A single-provider run cannot detect a provider value that leaked into the contract, which is the entire purpose of this test.
5. **Capability delta** — a provider that declares a capability as absent MUST return `status: unavailable` with a reason for affected evidence; silent omission is a failure.
6. **Counter-evidence discipline and referential integrity** — every `RankedHypothesis` carries `confidence`, `contradicting_evidence_refs`, and `counter_evidence_status`; `not_checked` fails a finalized result; every referenced `EvidenceId` exists in the same response and ids are unique within an invocation.

A test suite that never runs unattended is a claim, not a guarantee: the suite is wired into CI on every change to the contract, the profiles, or the adapter.

## Consequences

**Positive:** frontends and agent runtimes become replaceable; diagnostics standardized across clusters and operators; write path structurally impossible in Phase 1; identical contract across Talos and RKE2; results self-describing and joinable to their audit trail; potential platform differentiator (friendly assistant outside, RBAC-controlled agents inside).

**Negative / costs:** contract maintenance in the mother repo; OpenAPI + MCP adapter as one more indirection layer; risk of the contract lagging behind provider capabilities; every provider now owes identity handling, an invocation id, and a self-describing result, which makes a trivial provider slightly less trivial.

**Accepted Risks:** AR-1 (prompt injection — re-assessed: read-only scope bounds impact to information disclosure; evidence-ref rule and audit separation mitigate), AR-2 (GPU budget — provider-side inference on ok-gpu must respect existing limits).

## What we are NOT deciding

- Which agent framework OpenKubes "adopts" — none; the contract owns the boundary.
- Duplicate runbooks in frontend and runtime — runbooks live behind the contract.
- Any parallel/autonomous remediation by any component.
- Which identity provider issues consumer tokens, and how tokens map to consumer identities — provider profile values.

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

## Review resolutions (2026-08, revision 4)

Taken at spec level during OK-90 and recorded here so that this document and the normative OpenAPI agree.

| Question | Resolution | Where |
|---|---|---|
| How does a consumer authenticate, given that 401/403 are declared? | Consumer identity as bearer token, applied globally; explicitly not a Kubernetes credential; issuer/audience are provider values | `securitySchemes.bearerAuth`, `security` |
| How are the four audit artifacts joined without moving evidence? | `invocation_id` in every result body **and** in `X-Invocation-Id` on every response including errors; optional consumer-supplied `X-Request-Id` echoed into the invocation audit | `InvocationId`, `parameters.RequestId`, `headers.InvocationId` |
| A stored diagnostic result was not attributable | Results are self-describing: `cluster`, `namespace`, `workload`, `generated_at`, `effective_time_range` are required in `WorkloadInvestigation` and `EvidenceBundle` | both result schemas |
| A clamped `time_range` made results irreproducible | `effective_time_range` as an absolute `TimeWindow` (`start`, `end`) | `TimeWindow` |
| Hypotheses referenced evidence by `uri`, which is absent for unavailable evidence and not unique | Reference by `EvidenceId`; `id` is required on every `EvidenceRef`; referential integrity is a contract test | `EvidenceId`, `EvidenceRef.required` |
| Provider uncertainty was coerced into `unavailable` | `ClusterHealth.status` gains `unknown`, which must not be coerced to `unavailable` | `ClusterHealth.status` |
| No rule for what constitutes a breaking change | `/v1` is the compatibility major; `info.version` versions the document within it; suites pin `info.version` | `info.description` |
| Unbounded arrays in responses | `maxItems` on every array — for an LLM consumer an unbounded response is a cost and context risk, not only a denial-of-service surface | all array schemas |
| Two schema sources for a framework-generated provider | The generated document is not authoritative and is diffed against the normative file by contract test 1 | Contract Tests |

## Open for the final review

Revision 4 is review-ready, not accepted. The three-way review still owes:

1. **Sign-off on the revision-4 resolutions above.** They were taken while implementing OK-90 and have not been through a three-way round.
2. **Acceptance of the status transition** Draft → Accepted. After acceptance, add the editorial back-reference `Extended by: ADR-Platform-021` to ADR-Platform-015 (which is itself still `Proposed`, so the dependency order deserves one explicit sentence in the review).
3. **Confirmation that Phase 1 runs unauthenticated in practice**, or a decision on which identity provider issues consumer tokens for the first deployment. The contract now requires an identity; the first provider profile does not yet enforce one, and that gap should be a recorded decision rather than an oversight.
4. **RKE2 evidence.** The capability delta is declared for RKE2 but not yet measured on a running RKE2 provider (OK-95). Until it is, the Talos/RKE2 matrix rests on an assumption, and a wrong assumption would keep the tests green.
