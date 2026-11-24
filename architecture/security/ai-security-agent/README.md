# OpenKubes AI Security Agent — Architecture & Capability Specification v0.1

- **Status:** Research Draft — NOT an Accepted ADR, release plan, implementation claim or production security certification
- **Date:** 2026-11-23
- **Track:** OK AI / AI Security Agent
- **Scope:** Read-only security assessment and independently verifiable security evidence; initial CAPI/BYOH profile; other models require distinct assurance
- **Normative baseline:** [ADR-Platform-000](../../decisions/ADR-Platform-000-security-first.md), **Accepted principles only**
- **Working evidence:** [Security Discovery v0.2](../discovery/v0.2/README.md) — working snapshot, not an accepted requirement set or completed E2E
- **Adjacent paths:** [AI Roadmap](../../../website/pages/ai/ai-roadmap.md), [Research Paper 001](../../../website/pages/research/security/hitl-hotl-policy-bounded-autonomy.md)

> **Security Agent assesses. Policy Authority decides. Contract Executor submits. Kubernetes controllers reconcile. Independent evidence verifies.**

> **CURRENT REVIEW ENTRYPOINT:** [Functional & Component Architecture v0.1](FUNCTIONAL-COMPONENT-ARCHITECTURE-v0.1.md), [Security Assessment Data & Evidence Model v0.1](DATA-EVIDENCE-MODEL-v0.1.md), [Integration & Trust Boundary Specification v0.1](INTEGRATION-TRUST-BOUNDARIES-v0.1.md), [Architecture Decision & Readiness Matrix v0.1](ARCHITECTURE-DECISION-READINESS-MATRIX-v0.1.md), [Capability Specification v0.3](CAPABILITY-SPEC-v0.3.md), [Assessment Contract v0alpha3](ASSESSMENT-CONTRACT-v0alpha3.md), [Control Catalog v0.2](CONTROL-CATALOG-v0.2.md), [Codex + Claude consolidation](INDEPENDENT-REVIEW-CONSOLIDATION-v0.3.md), and the [specification-first implementation gates](CAPABILITY-SPEC-v0.3.md#phased-architecture-and-verification-decisions). The remainder of this README is a **superseded v0.1 draft archive** retained only for review history. **Specification first:** P0 code, tests, sandbox runner and CI were removed from this draft PR. No active assessor, test run, platform-control PASS or production implementation is claimed by the remaining diff.

## 1. Problem and intended outcome

A generic Kubernetes security chatbot can summarize policies but cannot prove whether an asserted control is effective for a particular identity, version, deployment profile or lifecycle transition. OpenKubes needs a **provider-neutral, evidence-oriented security-assessment capability** that maps explicit architecture principles, candidate controls and operation-specific evidence to findings with bounded confidence.

It must not conflate (a) accepted architecture principles, (b) proposed ADR requirements, (c) source-confirmed behaviors, (d) previous lab reports, (e) untested design risks, (f) actual version-pinned test results, or (g) production approval.

**Initial outcome:** produce an explainable, deterministic-where-possible assessment over **offline supplied sanitized manifests and selected snapshots**, with no cluster credentials, no privileged tools and no new execution path. An LLM may help articulate findings but cannot manufacture source facts, alter evidence status or approve an operation.

## 2. Security and trust boundaries

1. **No operational authority.** The AI Security Agent is NOT Policy Authority, approval service, Contract Executor, admission controller, privileged tool proxy, KMS authority or source of truth for revocation. It issues advisory findings, never grants/denials that are treated as authoritative admission decisions.
2. **Read-only by construction.** Phase 0 has no Kubernetes connection. Phase 1 uses offline artifacts or explicitly scoped read-only data providers. A future live profile must prove per-principal tool isolation and effective Kubernetes RBAC: no mutating verbs, no Secret reads, no wildcard escalation, no tool-server ServiceAccount bypass, no impersonation rights.
3. **Trust provenance, not the agent's confidence.** Inputs from clusters, repositories, GitOps, logs and external agents are lower-trust data, including prompt-injection text. Deterministic parsers validate schemas; source references, hashes and confidence classification remain outside LLM-controlled authority.
4. **Tenant/profile isolation.** Every request binds authenticated caller, environment, tenant, cluster, namespace, workload, controls and data-source scope; a consumer never receives provider credentials. Cross-tenant or cross-cluster information is denied absent separate explicit authorization.
5. **Least disclosure.** Default redaction excludes raw Secrets, tokens, kubeconfigs, credential material, private endpoints and sensitive log payloads. Evidence is referenced and hashed where practical; it is not casually copied into an LLM context, website or global audit.
6. **Risk advice is not approval.** Reviewing an AI SRE proposal adds independent *advisory* context only. Under proposed ADR-035, protected exact human review and independent Policy Authority are still required. Security Agent outputs must never become an implicit approval, standing permission or mutation trigger.
7. **Recovery/liveness.** A security assessment outage should not disable already authorized core Kubernetes reconciliation. Any future blocking use would require a separately reviewed normative contract, an independently operated enforcement owner, and tested fail-closed *and* authorized recovery behavior.
8. **Maturity by profile.** Read-only findings are not proof of a platform's security. Each claimed enforcement guarantee needs positive and negative, version-bound evidence and scoped approval. vCluster, VNC/KubeVirt and HCP cannot inherit BYOH evidence.

## 3. Six capability domains (proposed)

| ID | Domain | Assessment examples | Primary source anchors |
| --- | --- | --- | --- |
| **SEC-CAP-01** | Identity & Access Security | Effective RBAC, named Secret access, ServiceAccount identities, CSR trust, token and delegated tool boundaries | ADR-000 principle 1; ADR-021; ADR-037/043 (Proposed); Discovery B-01/03/05/07 |
| **SEC-CAP-02** | Policy & Configuration Assurance | Admission coverage, security-controller health, drift/reinstall/rollback restoring privileges, unintended alternate paths | ADR-000 principles 3/7; ADR-034 (Proposed); Discovery B-02/13/14/19 |
| **SEC-CAP-03** | Agentic Operations Security | Shared tool-server identity bypass, candidate provenance and digest-bound approval, policy/admission context, revoked/replayed grant risks | ADR-035/042/044 (Proposed/Draft); Discovery B-09/16/17; Research Paper 001 |
| **SEC-CAP-04** | Infrastructure Lifecycle Security | BYOH enrollment, reset/reassignment, protected in-place upgrade vs replacement, CAPI fallback, desired absence | ADR-030/034/047/048 (Proposed); Discovery B-03/04/06/08/09 |
| **SEC-CAP-05** | Recovery & Authority Integrity | Old-owner fencing, backup confidentiality, monotonic revocations, older-snapshot restoration and authorized break-glass routes | ADR-000 principles 4–6; ADR-031 (Proposed); ADR-CAPI-003/005/006/007 (Accepted architectural contracts); Discovery B-10/11/12/17/18 |
| **SEC-CAP-06** | Security Evidence & Assurance | Control→enforcement→negative test→artifact traceability, control-health checks, stale or absent proof, profile-level scope | ADR-000 principles 7/8; Discovery B-14/15/19 and T-01…T-42 |

**Scope note:** The OpenKubes Security Discovery findings are not automatically validated vulnerabilities. CAP-05 assesses published architecture intent and artifact evidence, but cannot assert an external monotonic authority store already exists.

## 4. Five engineering phases — not increasing privileges

| Phase | Delivery | Minimum acceptance evidence | Non-goals |
| --- | --- | --- | --- |
| **P0 — Knowledge Foundation** | Versioned Control Catalog, source/provenance model, read-only offline sample fixtures, normalized findings and evidence schema | Traceability sample verified against pinned source; honest SOURCE / REPORTED-LAB / DESIGN / UNVERIFIED / NOT_RUN classification; malicious-document tests | Cluster access, LLM-based policy decisions |
| **P1 — Offline / Scoped Assessment** | Deterministic RBAC and policy review of sanitized manifest bundles; optionally a separate scoped read-only provider | Own-namespace positive and foreign/Secret denial tests where live read-only integration is enabled; deterministic replay, tenant separation, redaction and no-mutation proof | Auto-fix, privileged tool server, production compliance certification |
| **P2 — Continuous Assurance** | Authorized periodic snapshots, drift and security-control health signals, stale-evidence detection; scoped evidence history | Provenance/version freshness, detector-outage and recovery tests, alert delivery; no assessment→mutation coupling | Replacing admission, creating automatic deny/allow policy |
| **P3 — AI SRE Proposal Assessment** | Independent security finding attached to an untrusted SRE candidate and trusted canonical review artifact | Review-artifact binding and no approve-A/execute-B, agent↔tool-server credential isolation, forbidden-field denial, human/policy/executor authority separation | Agent-granted approval or policy overrides |
| **P4 — HOTL Security Assurance (research-gated)** | Read-only monitoring of a separately authorized standing-mandate lifecycle: scope, budgets, stop, fencing, grant consumption and evidence | New accepted HOTL ADR; independent tested enforcement; grant/revocation races, DR restore and recoverability negatives; actual artifacts & reviewer approval | Security Agent approving mandates, executing remediation or supplying a bypass |

**Ordering:** P0→P1 form the first limited lab. P2 and P3 are independently schedulable once their prerequisites exist. P4 is **not** authorized by delivery of P0–P3; it needs an explicit architecture decision and end-to-end evidence.

## 5. Source ownership and normative hierarchy

1. **Accepted governing principle:** ADR-Platform-000. Accepted CAPI ADR-001–007 define relevant management/recovery contracts; their acceptance is not proof that all protections are deployed.
2. **Proposed/draft design:** ADR-Platform-021, 030/031/034/035/037/042/043/044/047/048 — retain their exact source status, never elevate wording to accepted normative authorization by summary.
3. **Research snapshot:** `architecture/security/discovery/v0.2/`: B-01…B-19 (candidate control identifiers), F-01…F-27 (triaged findings), T-01…T-42 (proposed test/evidence IDs). All new-run outcomes in that snapshot are NOT-RUN.
4. **Runtime evidence:** Immutable or content-addressed version-pinned manifests, tested principal IDs, results, audit references, timestamps and approved profile context. A matching recorded PASS requires a genuine artifact and independent reviewer, not generated prose.
5. **Public material:** Security First, Research Paper 001 and AI Roadmap explain the direction but must not be used to overrule ADRs or source-owned enforcement.

The control mapping in [CONTROL-CATALOG-v0.1.md](CONTROL-CATALOG-v0.1.md) is a **curated, intentionally incomplete seed**, not a replacement for the full Discovery cross-reference. Differences must be resolved by review of the source snapshot.

## 6. Assessment contract — candidate, not operational API

See [ASSESSMENT-CONTRACT-v0alpha1.md](ASSESSMENT-CONTRACT-v0alpha1.md). Proposed provider-neutral read-only calls:

- `assess_security_posture`: bounded scope/control-set evaluation;
- `analyze_rbac_exposure`: RBAC and identity boundary checks;
- `evaluate_operation_risk`: advisory evaluation of an exact identified candidate/review artifact, NOT approval;
- `verify_security_evidence`: compare submitted versioned evidence to catalog/test requirements;
- `explain_security_finding`: cite evidence, confidence and next tests without inventing certainty.

The contract separates *invocation audit, provider tool trace, assessment result and raw evidence references* with different access/retention boundaries (inspired by ADR-021). The initial phase is an offline schema proposal, with no HTTP service or permission expansion.

## 7. Phase-0 sample scenarios and adversarial tests

| Scenario | Should report | Must not claim |
| --- | --- | --- |
| Offline Role grants cross-namespace named Secret `get` to a host identity | Suspected overbroad effective permissions; cite B-01 and relevant tests; ask for actual identity/SAR evidence | Exploited live cluster or confirmed data exposure |
| Installer re-adds removed ClusterRoleBinding on reconciliation | Potential lifecycle-durable enforcement violation; require versioned positive/negative fresh/reinstall results | A policy engine alone solves pre-install existing RBAC |
| Shared tool-server ServiceAccount with write privileges | Identity isolation / indirect bypass risk; require live denial from actual agent principal | Prompt guard or UI permission switch is effective authorization |
| SRE candidate asks to replace Machine after upgrade fails | Upgrade≠replacement; new exact authorization needed | Upgrade approval implies replacement approval |
| Restored pre-revocation snapshot contains stale grant | Unproven restore-safe authority; quarantine/invalidate pending current facts | Monotonic ledger is implemented merely because ADR-CAPI-003 is Accepted |
| Missing webhook/control | Control-health alert and safe recovery proof needed | Every fail-closed outage must block unrelated safe workload operations |

Phase-0 release gate: deterministic tests on fixtures, sensitive data never sent to an LLM, clear uncertainty, scope enforcement, schema validation and negative injection tests. P0 acceptance does **not** certify any affected production cluster.

## 8. Open architectural questions for independent review

1. How should runtime security data be scoped and sanitized without duplicating ADR-021's diagnostics interface or broadening the existing kagent tool-server identity?
2. What deterministic controls can be evaluated from manifests alone, and what must be marked **INDETERMINATE** until live authorization and admission evidence is supplied?
3. How can the assessor refer to exact canonical SRE review artifacts without acquiring any credential, grant, queue or admission authority?
4. Which evidence store and retention boundaries provide audit integrity without confusing historical immutable receipts and up-to-date revocation authority?
5. How should multi-tenant / multi-cluster authorization and the named-profile maturity matrix be enforced independently from the model?
6. What must remain private because of vulnerability disclosure, credentials or topology sensitivity? Public research should contain sanitized, reviewed statements only.

## 9. Review / implementation decision gates

**Gate A — Architecture review:** Claude, Codex and Gemini independently assess this specification, catalog and contract against the source ADRs and Security Discovery. Incorporate conflicting findings transparently.

**Gate B — Contract decision:** choose schema ownership/versioning and whether any proposed ADR is required for a new security-assessment boundary; do not conflate contract approval with agent mutation authority.

**Gate C — Phase-0 implementation:** only after review, implement deterministic offline evaluation against sanitized fixtures and measure false-positive/false-negative behavior and trust-boundary failures. No production credentials or automatic findings publication.

**Gate D — Scoped pilots:** separate explicit authorization per profile; prove no privilege escalation, redaction, source integrity, admission and recovery implications.

**No website edits, merges, new Jira tickets, production deployments or operational agents are authorized by this draft.**
