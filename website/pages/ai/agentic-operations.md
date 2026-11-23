# Agentic Operations

**AI SRE proposes. Humans govern. Policies constrain. OpenKubes executes. Evidence verifies.**

OpenKubes distinguishes AI-generated recommendations from authorized infrastructure execution. The proposed AI SRE Agent may interpret an intent and submit an **untrusted candidate proposal**. A trusted canonicalizer derives an exact reviewable transition; the agent cannot become the authority that approves or executes its own change.

## Reference flow

1. **Intent** — interpret the operator's request.
2. **Candidate & canonicalization** — the agent submits untrusted candidate input; trusted components derive the exact canonical transition and a protected review artifact.
3. **HITL review & policy** — under the current proposed agentic path, a protected human approves the exact canonical transition. Independent policy evaluates scope and produces a bounded single-use grant.
4. **Execution & reconciliation** — the bounded executor verifies the grant, enforces typed fields and conditional acceptance; Kubernetes controllers reconcile accepted desired state.
5. **Evidence** — distinguish decision, acceptance, convergence and observed health independently of the agent's claims.

**HITL and HOTL are oversight models, not an autonomy ladder.** Future AI SRE HOTL would use revocable standing eligibility mandates and still require independent bounded execution; it needs a **new accepted normative ADR**, proven revocation and budget ordering, stop/fencing and recovery tests. A standing mandate is never permanent agent RBAC. The current agent-originated execution path is only a proposal, not a turnkey production service.

## Read more

- [Agentic Operations Reference Architecture](../agentic-operations-reference-architecture.md) — public design narrative.
- [Agentic AI PoC guideline](https://github.com/openkubes/openkubes/blob/main/docs/agentic-ai-poc-guideline.md).
- [Agentic AI evidence protocol](https://github.com/openkubes/openkubes/blob/main/docs/agentic-ai-poc-evidence-protocol.md).
- [OpenClaw component](openclaw.md).
- [Four-Agent AI Roadmap](ai-roadmap.md) — capability tracks, maturity and HITL/HOTL.\n- [Research Paper 001 — Policy-Bounded Autonomy](../research/security/hitl-hotl-policy-bounded-autonomy.md).\n- [OK AI overview](index.md).
