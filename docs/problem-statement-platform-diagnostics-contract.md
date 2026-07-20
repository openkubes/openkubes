# Problem Statement: Standardized Platform Diagnostics

**Status:** Reviewed in three-way review (Arash / Claude / GPT), revision 2 — Go issued 2026-07-17
**Origin:** OK-14 agentic AI evaluation (Daniel), escalated per agentic-ai-poc-guideline Part C
**Date:** 2026-07-17

## The problem

When a workload or platform incident occurs on an OpenKubes cluster, an operator today assembles a diagnostic picture manually: workload state, events, logs, network path (Cilium), and platform health (Prometheus). This takes 20–60 minutes of expert time, produces non-standardized output, and does not scale across clusters (ok-mgmt, ok1-talos, ok2-rmf, ok-shared) or across operators with different depths of platform knowledge.

## The forcing consumer

> An operator must, during a cluster incident, produce a standardized diagnostic report — workload state, events, logs, network, platform health — within minutes, from whatever surface they are working in.

This consumer is real today (incident handling on ok1-talos/ok2-rmf), recurs, and is surface-independent: the same report is needed from a CLI (`ok` — OK-76), a chat assistant, Slack, or a future incident workflow. It therefore forces a **contract**, not a tool choice.

A second, distinct consumer forces evidence collection as a public capability: **incident handoff, audit, and offline expert review** need raw evidence bundles without hypothesis generation.

## What is NOT the problem

- Choosing between agent frameworks (kagent, OpenClaw, or others). These are candidate implementation profiles and consumers, not the decision.
- Automated remediation. Any write path to clusters is explicitly out of scope and requires its own ADR per ADR-015.
- Replacing human diagnosis. The contract produces evidence and hypotheses; humans decide.

## Why now

OK-14 produced a concrete evaluation result: kagent is strong as a Kubernetes-native operations engine (RBAC per cluster/namespace/agent/tool, MCP tooling, A2A) but too heavyweight as an end-user entry point. Independently, a conversational frontend (OpenClaw) was evaluated for the personal-assistant role. Coupling the two directly (frontend skill → kagent-specific API) would create a provider-value dependency that fails the backend-swap test. The window to define the contract correctly is before the first integration is built, not after.

## Constraints (from committed ADRs and principles)

1. "OpenKubes owns the contracts, not the components" — the contract lives in `openkubes/openkubes`, not in any frontend's config or any agent framework's manifests. The normative contract is HTTP + OpenAPI; it must not exist only as MCP tool descriptions, or the semantic contract de facto belongs to the agent ecosystem.
2. "No structure without a forcing consumer" — Phase 1 scope is limited to what the two consumers above force; nothing speculative.
3. ADR-015 — write access to clusters requires a dedicated ADR with human approval; Accepted Risks AR-1 (prompt injection) and AR-2 (GPU budget) apply and must be re-assessed for this contract.
4. Kubernetes authorization stays in the cluster (RBAC at the provider), never in the consumer.
5. Real provider values (cluster endpoints, credentials, kagent manifests) live in `ok-cluster` (private), per the 2026-07-15 decision.
6. Talos vs. RKE2 differences are a provider capability delta, never a contract delta — providers declare capabilities and report unavailable evidence explicitly.

## Decision vehicle

ADR-Platform-021 — **Read-Only Platform Diagnostics Contract** (revision 3 attached). Component names appear only in Implementation Profiles and Rationale. The title deliberately avoids "Agent" (implies an implementation) and "AI-Assisted" (the ADR explicitly permits a non-LLM runbook/API provider). "Read-Only" remains correct through Phase 2: `propose_remediation` generates proposals but executes nothing.

## Success criteria

- A contract test can verify `investigate_workload` output schema against any provider, with no reference to kagent or OpenClaw.
- Swapping the provider (kagent → other agent runtime → plain runbook/API implementation) is invisible to consumers.
- Phase 1 grants zero write capability; this is verifiable from RBAC alone.
- Missing evidence is explicit (`status: unavailable` + reason), never silent.
- Every finalized hypothesis carries `counter_evidence_status` other than `not_checked`.

## Next step

Jira ticket as OK-14 successor: **"Finalize and validate the Read-Only Platform Diagnostics Contract."** First implementation (OpenClaw consumer + kagent provider profile) is a subtask, not the acceptance criterion of the main ticket.
