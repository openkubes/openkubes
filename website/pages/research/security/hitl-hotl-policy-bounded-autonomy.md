# Beyond Human-in-the-Loop: Policy-Bounded Autonomy for Kubernetes Operations

*From manual approvals to supervised, recoverable, and verifiable infrastructure automation.*

**Research Paper 001 · Reviewed Research · Editorial preview**

> **Research status:** This page establishes the scope and publication boundary for the first OpenKubes Research Paper. The full technical manuscript remains under editorial review; the architecture SVG is now included for review. This page is not a claim that HOTL execution has been implemented or production-approved.

## Research question

How can Kubernetes operations become more autonomous **without granting AI agents unrestricted infrastructure authority**?

HITL and HOTL describe modes of human participation and supervision. Policy-Bounded Autonomy describes the independent technical constraints that must limit execution authority. These are **orthogonal dimensions**, not three consecutive maturity stages.

## Proposed responsibility model

<figure class="ok-research-diagram">
  <a href="/research/security/policy-bounded-autonomy.svg" target="_blank" rel="noopener" aria-label="Open the Policy-Bounded Autonomy architecture diagram at full size">
    <img src="/research/security/policy-bounded-autonomy.svg" alt="Research architecture: current exact HITL review, trusted policy authority, bounded executor, conditional acceptance, Kubernetes reconciliation and independent evidence. The future HOTL standing mandate is research-only and requires a new ADR." loading="lazy">
  </a>
  <figcaption>Policy-Bounded Autonomy — research architecture, not a production deployment. Select the diagram to open the native SVG in full size.</figcaption>
</figure>

1. An untrusted agent performs permitted read-only diagnostics and submits a candidate proposal.
2. Trusted components canonicalize the exact change and produce a protected, human-visible review artifact.
3. Under the current proposed agentic path, an authorized human approves the exact canonical transition.
4. An independent Policy Authority evaluates that approval and issues a bounded, single-use authorization.
5. A deterministic Contract Executor verifies the authorization and submits to a declared Authority Profile for conditional desired-state acceptance.
6. Kubernetes controllers reconcile the accepted state; independently sourced evidence distinguishes authorization, acceptance, execution, convergence, and current health.

**Future research only:** Human-approved standing mandates might make narrowly bounded operations eligible for authorization without per-transition human review, but that would require a new normative ADR explicitly reconciling ADR-035. Such mandates must not become permanent agent RBAC.

## Open technical questions

- How do we bind the reviewed canonical artifact to the exact bytes accepted for execution?
- How do we prevent direct or indirect tool-server, workload-spec, or controller-trigger escalation?
- How do revocation, acceptance, and shared risk-budget reservations receive a provable ordering?
- How do single-use grants, retired identities, and owner fencing remain effective after management-plane restore?
- How do we preserve safety **and** a tested, independently authorized recovery path?

These questions are investigated in [OK-231](https://kubernauts.atlassian.net/browse/OK-231). The separate [OK-236 kind lab](https://kubernauts.atlassian.net/browse/OK-236) investigates bounded HITL/HOTL behaviors under isolated experimental conditions.

## Scope and maturity

**Accepted foundation:** [ADR-Platform-000](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-000-security-first.md) establishes security principles, not production certification.

**Proposed transition protocol:** [ADR-034](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-034-ok-up.md) and [ADR-035](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-035-hybrid-intent-and-control-plane-execution.md) describe exact authorization and required human review.

**Not proven:** General production HOTL, revocation-vs.-acceptance linearizability across all Authority Profiles, integrated cross-boundary fencing, and end-to-end management disaster recovery.

**Guiding principle:** Humans govern. Policies constrain. Machines execute. Evidence verifies.

[Back to Security & Trust Research](index.md)
