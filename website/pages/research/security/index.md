# Security & Trust Research

**Humans govern. Policies constrain. Machines execute. Evidence verifies.**

This area examines what it would take to make AI-assisted Kubernetes operations independently authorized, bounded, revocable, and verifiable.

## Research Paper 001

### [Beyond Human-in-the-Loop: Policy-Bounded Autonomy for Kubernetes Operations](hitl-hotl-policy-bounded-autonomy.md)

**Status: Reviewed Research.**

[View the full-size architecture diagram](policy-bounded-autonomy.svg) (native SVG; Research Only).

A technical investigation into Human-in-the-Loop (HITL), Human-on-the-Loop (HOTL), protected approvals, standing mandates, single-use transition grants, identity boundaries, independent evidence, and recoverable execution.

The existing proposed agent-originated mutation path still requires protected human approval of each exact transition. Broader HOTL execution is a **future research hypothesis**, not an accepted or production-validated capability.

The [four-agent AI Roadmap](../../ai/ai-roadmap.md) applies these boundaries to the proposed AI Assistant, Diagnostic, SRE and Security Agent capability tracks. The SRE track distinguishes exact HITL from future, separately approved HOTL; the Security Agent cannot act as Policy Authority.

## Related work

- [ADR-Platform-000 — Security First (Accepted principles)](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-000-security-first.md)
- [ADR-Platform-034 — Authorized Desired-State Transitions](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-034-ok-up.md)
- [ADR-Platform-035 — Agentic Lifecycle Boundary](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-035-hybrid-intent-and-control-plane-execution.md)
- **Risk-Based Autonomy & Durable Asynchronous Approval** — ongoing architecture research into authorization contracts, revocation and recovery.
- **kagent HITL/HOTL Security Lab** — isolated experimental validation of bounded agent operations and negative security tests.

**Evidence boundary:** An isolated lab PASS does not prove a production OpenKubes security guarantee. Unresolved authorization races, revocation ordering, budget consistency, and restore-safe authority remain research topics.
