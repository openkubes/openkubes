# ADR-Platform (Proposed): Hosted and External Agentic Operations with OpenShell

**Status:** Proposed — not accepted; subject to architecture review and [OK-220](https://kubernauts.atlassian.net/browse/OK-220) evidence  
**Date:** 2026-11-11  
**Decision owner:** OpenKubes Architecture  
**Number:** Pending allocation after repository ADR index review; this draft intentionally claims no unverified number.  
**Related:** ADR-Platform-001, ADR-Platform-015, ADR-Platform-021, ADR-Platform-030, ADR-Platform-034, ADR-Platform-035, ADR-Platform-039; OK-213, OK-220  
**Background:** [Agentic Operations Architecture Intent](https://kubernauts.atlassian.net/wiki/spaces/OpenKubes/pages/3167420417) and [Reference Architecture v0.1](https://kubernauts.atlassian.net/wiki/spaces/OpenKubes/pages/3167584257)

---

## Context

OpenKubes aims to support both platform-hosted AI agents and external AI agents. Secure execution of an agent is a separate concern from permission to change Kubernetes desired state. OpenShell is a promising *candidate* for the platform-managed secure-agent runtime, but its fit, security, maintainability, and integration have not yet been demonstrated in OpenKubes.

The current Agentic Operations reference architecture is **proposed**, not a claim of end-to-end implementation. It keeps agents non-authoritative, requires protected human review for agent-originated mutations, and reserves actual authorization, deterministic execution, desired-state acceptance, reconciliation, and independent evidence to existing OpenKubes contracts and controller owners. Core platform operations must remain usable without AI agents.

This ADR proposes how hosted/external agents connect to those boundaries. It does not silently change the existing accepted architecture.

## Decision drivers

- Offer first-class hosted AI agents **and** integrate independently operated external agents.
- Keep a single security and governance path regardless of agent runtime or framework.
- Reuse proven isolation/security runtimes rather than building another sandbox from scratch.
- Prevent prompt injection, credential access, egress and service-account escalation from becoming platform mutation authority.
- Preserve versioned OpenKubes-owned contracts, provider portability, and implementation replacement.
- Avoid coupling core OpenKubes, Developer Workspaces, or external agents to OpenShell.
- Remain compatible with pending MCP/CMCP architecture decisions in OK-213.

## Proposed decision

### 1. Support two modes

**Hosted agents** execute in an isolated, OpenKubes-managed runtime. **External agents** execute elsewhere and use authenticated, explicitly scoped, non-authoritative OpenKubes interfaces.

Both may access approved read-only diagnostics and submit candidate-only operation proposals. Neither gets implicit access to Kubernetes mutation, protected Git references, desired-state authority, approvals, grants, Contract Executor APIs, or reconciler ownership.

### 2. Evaluate OpenShell as the default hosted-agent runtime

OpenShell is the **preferred default-runtime hypothesis** for hosted agents, not an approved dependency. [OK-220](https://kubernauts.atlassian.net/browse/OK-220) must test tenant isolation, network and credential restrictions, resource limits, lifecycle and upgrades, security failure modes, observability, and operational costs. Alternatives remain viable until the evidence supports a decision.

OpenShell provides runtime boundaries; it is **not** the platform's policy authority, transition authorizer, Contract Executor, or evidence source of truth.

### 3. Share one OpenKubes-owned operations contract

Hosted and external agents enter through the same bounded logical contract boundary:

- Read-only diagnostics with explicit identity and scope.
- Candidate-only proposals treated as untrusted inputs.
- Server-attested origin and durable, tamper-evident provenance.
- Trusted validation, defaulting and canonicalization against the authoritative predecessor.
- Protected review of the exact, immutable semantic transition.
- Explicit authenticated human approval before agent-originated mutation.
- Independent policy evaluation and transition-bound, single-use authorization.
- Deterministic Contract Executor and compare-and-swap desired-state acceptance.
- Existing domain controllers (including CAPI/GitOps) owning reconciliation.
- Independently sourced evidence for immutable historical outcome, separate from current health.

No additional path from the agent runtime to authority mutation is permitted. Neither an agent success message nor an OpenShell audit event proves platform convergence.

### 4. Keep MCP/CMCP subordinate to the contract

MCP/CMCP may expose a carefully bounded projection of OpenKubes-owned versioned APIs and candidate interfaces. It must not become a new authority, broad mutating tool gateway, policy bypass, or second evidence truth.

The central-versus-federated MCP placement and implementation are deliberately **not decided here**; see OK-213. HTTP/OpenAPI contracts remain the normative baseline where the current architecture says so.

### 5. Preserve optionality at platform level and runtime replaceability

OpenKubes core remains functional when Agentic Operations and OpenShell are disabled. External agents do not need OpenShell to integrate. Hosted-agent deployments may select a conforming runtime profile; the public agent integration boundary must not expose OpenShell-specific assumptions as permanent platform contracts.

Developer Workspace isolation and lifecycle remain governed by ADR-Platform-039. A hosted agent is not automatically a DeveloperWorkspace and cannot inherit workspace capabilities implicitly.

## Logical architecture (not an implemented deployment)

```text
                  OpenKubes Console / CLI
              (review, approval, evidence UI)
                             |
           +-----------------+-----------------+
           |                                   |
    Hosted AI agents                    External AI agents
    OpenShell (candidate)               External runtime/framework
    sandbox & runtime policy            Authenticated ingress
           |                                   |
           +-----------------+-----------------+
                             |
          Read-only diagnostics / Candidate proposal
                (OpenKubes-owned contracts)
                             |
                TRUSTED OPENKUBES BOUNDARY
     Identity and server-attested provenance
        -> Trusted canonicalization + exact review
        -> Protected human approval + Policy Authority
        -> Single-use grant + Contract Executor
        -> CAS acceptance of desired-state revision
        -> Existing controllers / GitOps reconciliation
        -> Independent outcome evidence and current health
```

This diagram is a conceptual responsibility map, not an inventory of already deployed services.

## Alternatives

| Alternative | Benefit | Cost / trade-off |
| --- | --- | --- |
| A. OpenShell as default for hosted agents (preferred *hypothesis*) | Reuse sandbox/runtime controls and CNCF ecosystem technology | Security and operations require spike verification; possible runtime coupling |
| B. Another conforming sandbox provider | Portability and independent comparison | Potential feature or integration gaps |
| C. External agents only | Smallest managed-runtime footprint | Does not deliver the desired hosted-agent experience |
| D. Custom OpenKubes sandbox | Full implementation control | Large security, maintenance, and assurance burden |

The choice of runtime does not alter the trusted OpenKubes mutation protocol.

## Consequences

**Expected benefits:** A consistent security model across hosted and external agents; possible reuse of upstream runtime security features; lower custom sandbox engineering effort.

**New risks/costs:** Sandbox escape, credential or egress bypass, tenant-boundary errors, hosted-runtime lifecycle/availability, new audit correlation, release and dependency maintenance, and incomplete separation between runtime policy and operation authorization. These remain open until proven and reviewed.

## Validation and acceptance gates

This ADR **must stay Proposed** until:

1. OK-220 delivers a pinned, reproducible, non-production OpenShell evaluation, including install/upgrade/rollback and a threat model.
2. A hosted agent demonstrates bounded read-only diagnostics and candidate submission, without any direct mutating authority.
3. An external client demonstrates the *same* candidate-only path without requiring OpenShell.
4. Negative tests prove denial of direct Kubernetes writes, protected Git/Authority/Executor access, forbidden egress, credentials, and cross-tenant actions.
5. Approval, policy, single-use grant, CAS, controller reconciliation and independent evidence are exercised or explicitly recorded as **not yet proven**; no fabricated end-to-end PASS.
6. Fail-closed behavior, identity/provenance correlation, residual risks, operational costs and alternatives are recorded.
7. Conflicts with ADR-Platform-015/021/030/034/035/039 and OK-213 are resolved in architecture review.
8. A documented Go / Conditional Go / Defer / No-Go decision is made, an ADR number is allocated, and the accepted revision is merged separately.

## Explicit non-goals

- No production deployment or default-on setting approved by this ADR.
- No autonomous approval, remediation, rollback, direct Kubernetes mutation, or ambient cluster credentials for AI agents.
- No new mandatory control-plane service or central MCP decision.
- No replacement of Contract Executor, desired-state authority, CAPI, GitOps, or independent evidence.
- No implication that OpenShell is already integrated into OpenKubes.

---

**Guiding principle: AI thinks. OpenKubes executes. Evidence proves.**
