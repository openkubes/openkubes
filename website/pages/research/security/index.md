# Security & Trust Research

**Humans govern. Policies constrain. Machines execute. Evidence verifies.**

This area examines what it would take to make AI-assisted Kubernetes operations independently authorized, bounded, revocable, and verifiable.

## Research Paper 001

### [Beyond Human-in-the-Loop: Policy-Bounded Autonomy for Kubernetes Operations](hitl-hotl-policy-bounded-autonomy.md)

**Status: Reviewed Research — publication text under editorial review.**

A technical investigation into Human-in-the-Loop (HITL), Human-on-the-Loop (HOTL), protected approvals, standing mandates, single-use transition grants, identity boundaries, independent evidence, and recoverable execution.

The existing proposed agent-originated mutation path still requires protected human approval of each exact transition. Broader HOTL execution is a **future research hypothesis**, not an accepted or production-validated capability.

## Related work

- [ADR-Platform-000 — Security First (Accepted principles)](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-000-security-first.md)
- [ADR-Platform-034 — Authorized Desired-State Transitions](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-034-ok-up.md)
- [ADR-Platform-035 — Agentic Lifecycle Boundary](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-035-hybrid-intent-and-control-plane-execution.md)
- [OK-231 — Risk-Based Autonomy & Durable Asynchronous Approval](https://kubernauts.atlassian.net/browse/OK-231)
- [OK-236 — kagent HITL/HOTL Security Lab](https://kubernauts.atlassian.net/browse/OK-236)

**Evidence boundary:** An isolated lab PASS does not prove a production OpenKubes security guarantee. Unresolved authorization races, revocation ordering, budget consistency, and restore-safe authority remain research topics.
