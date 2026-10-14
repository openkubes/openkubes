# Agentic Operations

**AI Thinks. OpenKubes Executes. Evidence Proves.**

OpenKubes distinguishes AI-generated recommendations from authorized infrastructure execution. An agent may interpret an intent or propose an operation, but it must not be the authority that silently approves and executes arbitrary changes.

## Reference flow

1. **Intent** — interpret the operator's request.
2. **Proposal** — create a structured operation proposal bound to contracts.
3. **Policy & authorization** — check the proposed operation and require appropriate authorization.
4. **Execution & reconciliation** — let the authorized, bounded execution path act on Kubernetes.
5. **Evidence** — capture verifiable outcomes independently of the agent's success claim.

These are architectural boundaries and a direction of development; they are **not** a claim that the complete autonomous workflow is available as a turnkey feature today.

## Read more

- [Agentic Operations Reference Architecture](../agentic-operations-reference-architecture.md) — public design narrative.
- [Agentic AI PoC guideline](https://github.com/openkubes/openkubes/blob/main/docs/agentic-ai-poc-guideline.md).
- [Agentic AI evidence protocol](https://github.com/openkubes/openkubes/blob/main/docs/agentic-ai-poc-evidence-protocol.md).
- [OpenClaw component](openclaw.md).
- [OK AI overview](index.md).
