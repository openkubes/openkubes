# ADR-Platform-035: Hybrid Intent and Control-Plane Execution Architecture for Cluster Lifecycle Management

**Date:** 2026-08-18

**Status:** Proposed

**Extends:** ADR-Platform-015

**Applies:** ADR-Platform-030

**Constrained by:** ADR-Platform-034

**Related:** ADR-Platform-001, ADR-Platform-004, ADR-Platform-021, ADR-Platform-023

---

## Context

OpenKubes integrates an agentic AI layer through replaceable implementations such as
OpenClaw and kagent. That layer can improve cluster-lifecycle authoring by interpreting
natural-language intent, requesting read-only diagnostics, and preparing candidate
changes for workload clusters across the selected CAPI infrastructure, control-plane,
bootstrap, and OS Implementation Profiles.

An LLM is, however, an untrusted and non-deterministic authoring participant. Prompt
injection, poisoned retrieval context, ambiguous user intent, or model error must not
weaken the control-plane guarantees established by ADR-030 and ADR-034. In particular,
an agent must not become an authority, policy decision-maker, Contract Executor, or
reconciler merely because it can call tools.

OpenKubes therefore needs to define how an optional agentic authoring overlay connects
to the existing lifecycle control plane without turning a model, prompt, MCP tool, local
runner state, or candidate Git branch into a competing source of truth.

## Decision

OpenKubes adopts a hybrid interaction model while preserving the Cluster Lifecycle
Control-Plane Execution Model from ADR-030.

LLM-based agents operate only as optional, untrusted authoring consumers. They may
interpret intent, invoke approved read-only diagnostics, and submit candidate Contract
input. They **MUST NOT**:

- authorize a transition;
- accept authoritative desired state;
- invoke mutating Contract Executor or Authority operations;
- write to a desired-state authority path;
- execute provider-specific mutations; or
- participate as a controller in infrastructure, Cluster Enablement, or platform
  reconciliation.

Every agent-originated state-changing proposal must pass through the same versioned,
machine-verifiable Contract, Policy, Authority, Contract Executor, and controller
boundaries as any other lifecycle request. The agentic path does not create a second
transition model or a privileged shortcut around `ok up` semantics.

### 1. Roles and execution sequence

The agent-originated lifecycle path is:

1. **User / AI Agent** produces untrusted candidate authoring input or a proposed patch.
2. **Candidate Proposal service** authenticates the submitting workload identity and
   records server-attested, tamper-evident provenance outside fields writable by the
   agent. Self-asserted provenance metadata is not trusted.
3. **Trusted Canonicalizer / Planner** parses, defaults, validates, and canonicalizes
   the candidate, generates the trusted transition identity, and derives the exact
   semantic transition from the current authoritative revision to the requested
   canonical revision.
4. **Human Approver** performs an authenticated and durable approval action through a
   protected review system. Verbal or otherwise non-recorded approval does not satisfy
   this requirement. The approval artifact binds the exact canonical request digest and
   transition identity presented for review.
5. **Policy Authority** verifies the protected human approval, evaluates automated
   policies, and issues a protected authorization decision bound to the exact transition,
   validity window, audience, and permitted use count.
6. **Contract Executor** independently verifies the authorization and all point-of-use
   preconditions, then durably claims the authorization in the execution ledger before
   the first possible desired-authority mutation. It invokes the selected Authority
   Profile and records claim, submission, and observation evidence under the exact
   transition identity.
7. **Authority Profile** atomically accepts the requested revision through the
   compare-and-swap semantics of ADR-034 and durably correlates the accepted authority
   state with the transition and authorization that established it.
8. **Responsible controllers** reconcile the accepted desired state asynchronously and
   publish their domain-specific status.
9. **OpenKubes Status Aggregator** publishes normalized, revision- and
   generation-correlated Conditions. The **Durable Evidence Store** retains historical
   transition proof according to the normative retention policy.

The protected transition and authorization binding follows ADR-034 and covers at least:

```text
transitionID
fromRevision
toRevision | DESIRED_ABSENT
operation
requestDigest
validity window
audience
permitted use count
```

The immutable acceptance identity additionally includes the resulting
`authorizationDigest` as required by ADR-034.

Consistent with ADR-034 §7–§8, an acceptance authorization is **single-use**: its
`permitted use count` is `1`. A distinct transition requires a distinct authorization;
a consumed grant is never replayed to accept another revision.

```text
User / AI Agent
        |
        v
untrusted candidate input
        |
        v
Candidate Proposal service
  authenticates source and records server-attested provenance
        |
        v
trusted canonicalization and transition planning
        |
        v
authenticated, durable human approval of the exact request
        |
        v
Policy Authority verifies approval and authorizes exact transition
        |
        v
Contract Executor verifies and durably claims authorization
        |
        v
Authority Profile performs atomic CAS acceptance
        |
        v
GitOps / lifecycle / Enablement / platform controllers reconcile
        |
        v
revision-correlated Conditions and historical transition outcome

Cross-cutting durable records:
  Policy decision | Executor claim/submission | Authority acceptance | Evidence
```

### 2. State and evidence ownership

Agent integration does not collapse the orthogonal state spaces defined by ADR-034.
Ownership remains:

| State or record | Owner |
|---|---|
| Candidate content and server-attested origin | Candidate Proposal service |
| Human approval record | Protected review system |
| Authorization decision | Policy Authority |
| Claim, submission, and observation evidence | Contract Executor and execution ledger |
| Authoritative desired revision and acceptance correlation | Selected Authority Profile |
| Domain-specific observed status | Responsible controllers |
| Normalized aggregate Conditions | OpenKubes Status Aggregator |
| Historical transition proof | Durable Evidence Store |

None of these records may become a substitute for another. In particular, a human
approval is not authority acceptance, successful Executor submission is not convergence,
and an LLM interpretation of status is not a platform Condition.

### 3. Strict human approval for agent-originated changes

Every agent-originated state-changing proposal **MUST** receive explicit human approval
of the exact canonical request digest and protected transition identity before the Policy
Authority may authorize it. Automated policy evaluation may additionally constrain or
reject the proposal, but it must not substitute for human approval.

Human approval is only meaningful if the human reviews the semantic transition rather
than an opaque hash. The review artifact is a trustworthy, deterministically derived
representation of the canonical request — not the canonical bytes themselves — and both
must be bound into the approval:

> The protected approval artifact MUST bind the canonicalization profile and version, the
> review-renderer version, and a digest of the immutable human-visible review artifact. The
> review artifact MUST be deterministically derived from the exact authoritative predecessor
> and requested canonical revision, including effective defaults. The reviewed semantic
> transition, canonical request digest, and accepted revision MUST remain inseparably
> correlated. An opaque digest alone is not sufficient human-review evidence.

That binding is only sound if canonicalization is unambiguous. The Trusted Canonicalizer
(§1) is a trusted component parsing untrusted agent input, and must not admit
parser-differential or canonicalization ambiguity:

> Canonicalization MUST be deterministic, versioned, and unambiguous. Identical semantic
> input MUST produce identical canonical bytes and digest; ambiguous fields, duplicate
> keys, unsupported schema versions, and parser-dependent representations MUST be rejected.
> No component may reinterpret or re-canonicalize the approved request under different rules
> after approval.

The agent may use a narrowly scoped identity to create a proposal or reviewable pull
request. It must not be able to:

- approve or merge the proposal;
- update protected branches or authoritative Git refs;
- create, alter, or impersonate human approval records;
- alter server-attested provenance;
- write to an API-backed Authority Store; or
- cause a candidate branch or proposal store to be reconciled by active controllers.

A modification after human review changes the canonical request digest and invalidates
the approval and any authorization derived from it. Autonomous approval of
agent-originated transitions requires a separate ADR with an explicit threat model,
operation scope, authorization model, and acceptance evidence.

Scoped standing approvals are intentionally excluded from this ADR:

> Scoped standing approvals, pre-authorized transition classes, and policy-only approval
> of agent-originated changes are intentionally out of scope. They constitute autonomous
> approval and require a separate ADR.

### 4. Authority and GitOps boundary

Candidate storage is not desired-state authority. Candidate branches, pull requests,
and proposal records must be structurally separated from all refs and objects watched by
active GitOps or lifecycle controllers.

For a Git-backed Authority Profile, ordinary local Git commands, an unconditional push,
or a conventional merge without transition correlation do not by themselves satisfy
ADR-034. Acceptance must conditionally update the declared authoritative ref from the
expected predecessor and inseparably preserve the authorization and transition
correlation. Argo CD or another GitOps Implementation Profile reconciles only the
accepted authority path.

For an API-backed Authority Profile, the same semantics apply through a server-enforced
resource version or equivalent atomic precondition. The selection of a Git-backed or
API-backed profile is outside this ADR.

### 5. Agent-facing MCP projection

The Model Context Protocol is an optional adapter and is not a source of platform
semantics or authorization.

- The Cluster Lifecycle Contract and transition schemas remain canonical, versioned,
  OpenKubes-owned artifacts independent of transport.
- Read-only diagnostics exposed to an agent derive from the Read-Only Platform
  Diagnostics Contract in ADR-021.
- Candidate submission exposed to an agent derives from a separate, versioned,
  non-authoritative Candidate Proposal Contract.
- The agent-facing MCP surface must not be created by subtracting selected methods from
  the mutating Contract Executor or Authority APIs.
- Mutating Executor and Authority operations require separate identity, authorization,
  and network enforcement boundaries and must not appear in the agent-facing MCP
  surface.
- MCP schemas should be mechanically generated from, or mechanically verified against,
  the reviewed agent-facing contracts.
- Prompts, tool descriptions, and model behavior are never normative validation,
  provenance, policy, authorization, or readiness logic.

The Candidate Proposal Contract schema and transport are separate versioned contract
work. This ADR establishes its security role and non-authoritative boundary, not its
final API shape.

### 6. Contract Executor implementation

The current Go/Python runner is the initial implementation profile for the Contract
Executor role. It remains non-authoritative and replaceable by any conforming non-LLM
implementation. This ADR protects the deterministic Executor boundary; it does not make
the current runner a permanent platform component.

All externally observable Executor operations must be retry-safe under the exact
transition identity and implement the `ACCEPTED`, `ALREADY_ACCEPTED`,
`PRECONDITION_FAILED`, and `INDETERMINATE` semantics from ADR-034. Executor process
termination or a successful exit code is not lifecycle success.

Live convergence is determined only by the selected profile's declared, revision- and
generation-correlated Conditions and normalized OpenKubes aggregate Conditions. It is
never determined by an LLM response or by Executor submission logs.

### 7. Normative invariants

The load-bearing security properties above are named so downstream ADRs and conformance
tests can cite them directly. They are implementation-neutral MUST statements; the
Acceptance criteria prove them by evidence.

- **INV-035-1 — Provenance isolation.** Server-attested candidate provenance MUST be
  recorded outside any field the agent can write, and MUST NOT be self-asserted. *(AC 1)*
- **INV-035-2 — Identity isolation.** Agent credentials MUST NOT write to the Authority
  Store, protected Git refs, human approval records, lifecycle resources, or mutating
  Executor endpoints. *(AC 2)*
- **INV-035-3 — Reconciliation isolation.** Candidate branches and proposal stores MUST
  lie outside every active GitOps and lifecycle controller watch path. *(AC 3)*
- **INV-035-4 — Human-approval enforcement.** No agent-originated transition may be
  authorized without a valid, authenticated human approval binding, regardless of
  automated policy outcome. *(AC 4)*
- **INV-035-5 — WYSIWYS approval binding.** The approval MUST bind the canonicalization
  profile/version, the review-renderer version, and a digest of the immutable
  human-visible review artifact, keeping the reviewed transition, canonical request digest,
  and accepted revision inseparably correlated; an opaque digest alone is not human-review
  evidence. *(AC 11, 12)*
- **INV-035-6 — Deterministic canonicalization.** Canonicalization MUST be deterministic,
  versioned, and unambiguous; ambiguous or parser-dependent representations MUST be
  rejected and MUST NOT be re-canonicalized under different rules after approval.
  *(AC 13, 14)*
- **INV-035-7 — Digest and transition lock.** Only the exact approved canonical request
  and transition identity may be authorized and accepted; any post-review modification
  invalidates the approval. *(AC 5)*
- **INV-035-8 — Single-use authorization.** An acceptance authorization is single-use and
  bound to the exact transition; stale or out-of-sequence acceptance MUST fail closed
  with `PRECONDITION_FAILED`. *(AC 6, 7)*

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Agent writes CAPI, Crossplane, provider, or Authority resources directly | Bypasses human approval, policy, atomic acceptance, and the Executor boundary; makes prompt and tool behavior part of the trusted control plane |
| Agent invokes the full Executor API and relies only on RBAC to deny mutation | Exposes unnecessary mutating semantics to the agent surface and makes a single authorization error or confused-deputy path high impact |
| MCP tool definitions are the canonical lifecycle contract | Transfers platform semantics to an agent protocol and prompt ecosystem, contradicting ADR-001 and ADR-021 |
| No AI-assisted lifecycle authoring | Preserves the existing control plane but forgoes useful intent translation and candidate preparation; read-only diagnostics from ADR-021 would remain available |
| Automated policy substitutes for human approval | Violates the ADR-015 human-merge boundary for agent-originated changes; autonomous approval requires a separate threat model and decision |

## Consequences

### Positive

- Agent frameworks and the current runner remain replaceable behind OpenKubes-owned
  contracts.
- An LLM compromise cannot by itself authorize a transition, change desired-state
  authority, or call a mutating lifecycle operation.
- Human review is bound to the exact canonical request rather than mutable prose or a
  branch name.
- Candidate, authorization, acceptance, execution, convergence, and historical outcome
  remain independently auditable.
- Provider-specific reconciliation stays below the Contract and Implementation Profile
  boundaries.

### Costs and risks

- The authoring path requires proposal storage, protected review, policy, atomic
  acceptance, durable ledgers, and evidence correlation.
- Human approval may become a throughput bottleneck for frequent lifecycle changes.
- Compromised agents can still create undesirable but non-authoritative proposals,
  consume proposal capacity, or disclose information available to their read identity.
  Candidate creation therefore requires least privilege, audit, rate limits, quotas, and
  bounded retention.
- Poisoned retrieval context or read-only diagnostic content can influence the model's
  next candidate, forming a prompt-injection feedback loop. Mandatory human approval of
  the exact canonical request bounds but does not eliminate this risk: a manipulated
  candidate cannot become authoritative without an authenticated human approving the exact
  semantic transition, though a human can still be deceived into approving a manipulated
  candidate. Diagnostic inputs are never normative validation, policy, or authorization.
- Transition IDs, revision digests, authorization digests, and resulting evidence must
  be durably correlated and retained according to the normative evidence retention
  policy. Correlation required to interpret the current authoritative revision or
  resolve recovery must not expire while that dependency exists.
- The diagnostics, candidate, Executor, and Authority API surfaces require independent
  compatibility and security tests.

## Acceptance criteria

This ADR may advance from `Proposed` only when reviewed evidence and automated tests
demonstrate at least:

1. **Provenance isolation:** The Candidate Proposal service authenticates the submitting
   workload and records server-attested, tamper-evident provenance that the agent cannot
   create, modify, or impersonate.
2. **Identity isolation:** Agent credentials cannot write to the Authority Store,
   protected Git refs, human approval records, cluster lifecycle resources, or mutating
   Contract Executor endpoints.
3. **Reconciliation isolation:** Candidate branches and proposal stores are outside all
   active GitOps and lifecycle controller watch paths.
4. **Human-approval enforcement:** An agent-originated proposal without a valid,
   authenticated human approval binding is rejected even when all automated policies
   pass.
5. **Digest and transition lock:** Only the exact human-approved canonical request and
   transition identity can be authorized and accepted. Any post-review modification
   invalidates the approval or causes authorization verification to fail.
6. **Stale-write rejection:** A conflicting or out-of-sequence acceptance request returns
   `PRECONDITION_FAILED` without changing authoritative desired state.
7. **Replay and recovery safety:** Replays, Executor crashes, and lost responses resolve
   under the exact transition identity without duplicate acceptance or uncontrolled
   mutation, including correct `ALREADY_ACCEPTED` and `INDETERMINATE` handling.
8. **MCP attack-surface verification:** The published MCP schemas and runtime tool
   enumeration expose no mutating or authorizing Executor or Authority operations, and
   agent credentials are denied if such an endpoint is addressed directly.
9. **Restart recovery:** A restarted Executor resumes observation and evidence collection
   from durable Authority and ledger state using the correlated transition identity; no
   Executor-local state is required to preserve desired authority.
10. **Condition correctness:** Convergence is derived from the selected profile's
    declared revision- and generation-correlated Conditions, and later health changes do
    not rewrite an immutable historical transition outcome.
11. **Semantic review, not hash review:** The human reviewer is presented with the
    semantic transition, including effective defaults, and not merely a digest.
12. **Canonical-form correlation:** The review representation is demonstrably derived from
    the exact canonical predecessor and requested revision; canonical bytes,
    schema/canonicalizer version, review-artifact digest, request digest, and accepted
    revision remain correlated.
13. **Parser-differential resistance:** Different parsers or serializations cannot yield
    a divergent semantic transition under the same approval; ambiguous or unsupported
    representations are rejected at canonicalization.
14. **Renderer/canonicalizer binding:** Any change to the canonicalization profile,
    canonical object, or bound human-visible review artifact changes its protected binding
    and requires re-approval. A later renderer deployment does not invalidate an immutable,
    versioned review artifact already bound to an approval.

## Re-evaluation triggers

- Autonomous approval of agent-originated changes is proposed.
- An agent is proposed as a Policy Authority, Contract Executor, Authority Profile, or
  reconciler.
- Mutating operations are proposed for an agent-facing MCP surface.
- Candidate storage is proposed as a desired-state authority path.
- The human-approval requirement materially prevents a required operating model; any
  relaxation requires a new threat model and decision rather than an implementation
  exception.
