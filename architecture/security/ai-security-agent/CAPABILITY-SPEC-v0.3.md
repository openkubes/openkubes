# AI Security Agent — Capability Specification v0.3

**Status:** Research draft, not Accepted or production-approved. **Reviewed inputs:** source-read Codex v0.1 REVISE (SA-01…09) and source-read Claude v0.1 REVISE (R-01…09). The [consolidated dispositions](INDEPENDENT-REVIEW-CONSOLIDATION-v0.3.md) compare those v0.1 comments to v0.2, without claiming the v0.3 revision was independently re-reviewed.

**Governing sources:** [ADR-Platform-000](../../decisions/ADR-Platform-000-security-first.md) (Accepted *principles*), [Security Discovery v0.2](../discovery/v0.2/README.md) (working research), [Control Catalog v0.2](CONTROL-CATALOG-v0.2.md) (source-reconciled projection), [Assessment Contract v0alpha3](ASSESSMENT-CONTRACT-v0alpha3.md) (candidate, non-normative). The original Accepted CAPI-001–007 architecture contracts govern their respective profiles, but acceptance does not demonstrate deployed controls.

> **Assessor analyzes evidence. Humans review. Independent Policy Authority authorizes. Contract Executor acts. Controllers reconcile. Independent observations verify.**

## Capability scope

Six proposed domains, individually gated: **SEC-CAP-01 Identity & Access**, **02 Policy & Configuration Assurance**, **03 Agentic Operations Security**, **04 Infrastructure Lifecycle**, **05 Recovery & Authority Integrity**, **06 Evidence & Assurance**. All are **read-only advisory**. The agent cannot create or redeem approvals, grants, authorization decisions, controller-watched intents, stop/pause/revocation requests or break-glass credentials. An absence, failure or negative opinion of the assessor never automatically blocks legitimate operations or recovery. Separately enforced policy remains fail-closed where authority cannot be verified.

### P0 — Deterministic offline foundation

**Minimum useful behavior:** one synthetic B-01 **declared-RBAC binding** case and one explicit insufficient-evidence report. Consume a single bounded, strict-JSON bundle supplied as bytes to the process, with a source-pinned B-01→F-01/F-25 and T-01…04 mapping. A declared Role alone grants nothing: assess binding references and a declared rule, but do not claim **effective Kubernetes authorization**. P0 has no model, cluster access, credentials, network API, resolver, or arbitrary filesystem access.

**Safety and quality gates:** unknown fields, keys/IDs, duplicate JSON keys, malformed content, oversized input, traversal/URI strings, secrets and ambiguous/unclassifiable data must be **rejected safely**, with no echo of supplied secrets. Embedded prompts are inert input, never instructions; output is fixed, structured advisory data. The bounded adversarial corpus must have **zero critical false negatives**, which means no case can cause unauthorized access, unsafe disclosure, model instruction execution or a false platform PASS; publish exact case counts and limitations rather than ungrounded 99% accuracy. Tests of JSON parsing alone do **not** prove process isolation: verify unprivileged execution, no ambient credentials, network, host mounts and writable host paths independently.

**P0 exit:** deterministic declared observation and `INSUFFICIENT_EVIDENCE`; every actual platform-control test remains `NOT_RUN`, every profile approval `NOT_APPROVED`, every severity `UNASSESSED`. P0 test-suite success is not platform security evidence.

### P1 — Extended offline first; live pilot separately gated

Expand offline binding/aggregate analysis; incomplete RBAC inventory never establishes absence of effective access. The three ADR-021 diagnostics functions **do not expose** RBAC bindings, CSR state, effective permissions, SubjectAccessReview (SAR), or Secret scope. A future live security-data consumer needs a separately reviewed OpenKubes-owned typed, capability-declared *security observation* interface or distinct scoped provider: the existing ADR-021 get/list/watch identity must **not** gain SAR `create`, impersonation, arbitrary direct API or privileged tool-server operations. Backend authorizes original principal, real service identity, tenant, immutable target, observation class, evidence handle and recipient at every hop. Actual-principal positive/negative requests, no Secret access and no write/impersonation escalation must be proven before any live permission assurance.

### P2 — Continuous Security Assurance

Only pre-authorized bounded observations; report drift, stale or missing control evidence, detector health and alerts. Evidence receipt integrity, current health and **current rollback-resistant revocation/ownership/grant facts** are different trust domains. A source SHA establishes bytes, not authenticated producer/reviewer, freshness or sequence completeness. External verification requires a reviewed independent tamper-evident authority or demonstrably equivalent trust; reuse established CAPI ownership/evidence architecture where applicable rather than inventing a new authority. The assessor cannot itself assert current fencing, restoration safety or independently verified PASS.

### P3 — AI SRE proposal review

Candidate-only advice binds to the candidate digest and remains **preliminary**. A canonical-transition assessment requires a verified immutable review projection bound to original caller, tenant, target, effective predecessor, toRevision, operation, transition ID, canonicalization profile/version, renderer version, reviewed artifact and request digests, and applicable execution profile. Advisory findings are presented **separately** from the protected semantic review and cannot modify its digest or approval record. Only trusted protected human review, independent Policy and Executor paths may decide or mutate; they function with the assessor absent.

### P4 — HOTL evidence monitoring (research only)

Standing mandates and agent-initiated HOTL mutation require a **new accepted normative ADR**, independent authority with documented revocation/expiry/budget/acceptance ordering and stop/fencing/recovery proofs, and profile-specific negative E2E. Neither v0.3 nor progress through P0–P3 authorizes HOTL. The Security Agent remains an advisory observer; it does not stop operations, grant mandates or execute recovery.

## Disclosure and output handling

Public source repositories are **intentional**; their visibility alone is not an incident. However, detailed unpublished vulnerability findings, credential material, private operational metadata and potentially exploitable paths require restricted security-maintainer intake, independent verification, coordinated owner/upstream review and an explicit safe public projection. Remove private trackers, secrets, reusable evidence handles, customer identities and topology from exported reports. Apply safe projection **before any stdout, log, exception, cache, model context, notification or website export**. P0 uses fixed finding classes and `UNASSESSED` severity; no generated score.

## Phased architecture and verification decisions

| Gate | Proof required | Not established here |
| --- | --- | --- |
| P0 | Fixed bounded fixture, deterministic parser/validator, adversarial no-leak corpus, independent runtime isolation | Live RBAC, E2E security control PASS |
| Live P1 | Consumer/observation contract, authenticated per-hop delegation, actual identity negative tests, Secret exclusion | Reuse of ADR-021's three functions for SAR/impersonation |
| P2 | Independent producer/reviewer, historical/current separation, detection, outage and recovery evidence | Existence of external security/evidence store |
| P3 | Protected canonical review and exact transition binding, independently owned approval/grant/acceptance proof | Findings as approval or blocking predicate |
| P4 | New Accepted HOTL ADR and independent actual execution/DR/concurrency E2E | Any HOTL authorization |

The normative service technology for a future network API remains a **separate decision**. If a service is approved, the semantic schema must be **OpenKubes-owned and specified in versioned OpenAPI/HTTP** (consistent with ADR-021 direction), with MCP/CMCP only an optional thin adapter. The P0 offline evaluator does not require HTTP/OpenAPI at all.

**Known limitations:** Source Discovery F/T records are research; all new Discovery T-* run outcomes in the reviewed snapshot are NOT_RUN. Claude/Codex did not execute platform tests. This document and any subsequent isolated P0 test do not certify runtime controls or production readiness.
