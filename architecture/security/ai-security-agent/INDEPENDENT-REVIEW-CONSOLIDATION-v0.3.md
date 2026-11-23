# AI Security Agent — Independent Review Consolidation v0.3

- **Status:** Architecture research, editorial disposition; **not** an accepted security architecture, independently verified implementation or production assurance.
- **Review evidence:** Codex source-read v0.1 REVISE (SA-01…SA-09) and Claude source-read v0.1 REVISE (R-01…R-09); both inspected pinned `openkubes/openkubes` and Accepted CAPI ADRs; neither ran a platform control test.
- **Version discipline:** Claude and Codex both reviewed **v0.1**, so their findings must be assessed against our post-Codex **v0.2**, rather than interpreted as proof that v0.2 failed. Gemini's access-blocked review remains separate and is not counted as source verification.
- **Current review targets:** [Capability Specification v0.3](CAPABILITY-SPEC-v0.3.md), [Assessment Contract v0alpha3](ASSESSMENT-CONTRACT-v0alpha3.md), [Control Catalog v0.2](CONTROL-CATALOG-v0.2.md).

## Codex dispositions carried forward

| Finding | v0.3 treatment | Implementation evidence |
| --- | --- | --- |
| SA-01, SA-09 | Single bounded synthetic input bundle; package-local IDs, no resolver or ambient credentials; P0 is intentionally minimal | Initial offline parser/fixture tests do not establish OS sandboxing |
| SA-02, SA-07 | Source confidence, record verification, historical outcome, applicability, current health, monotonic authority and profile approval are different fields | External trust and restore tests deferred |
| SA-03 | One row per B ID, direct F/T edges extracted from source tables; gate dependencies separate; T-21 caveat visible | Mapping checks subject to independent acceptance |
| SA-04 | Live authenticated delegation, typed observations, backend and output per-hop authorization; no arbitrary SAR/Secret proxy | Future live pilot only |
| SA-05 | Preliminary candidate advice distinct from canonical semantic review; non-redeemable references; exact immutable bindings | Future P3 only |
| SA-06 | No findings-as-policy/approval/gate, stop/revoke, controller-watched trigger, or recovery dependency | Later negative tests needed |
| SA-08 | Restricted disclosure and safe projections before logging, cache, export or publication; severity UNASSESSED | Release/disclosure owner not yet appointed |

See [SA-01…SA-09 full disposition](CODEX-REVIEW-DISPOSITION-v0.2.md).

## Claude findings assessed against v0.2

| ID | Claude severity | v0.2 status | v0.3 disposition | Remaining gate |
| --- | --- | --- | --- | --- |
| **R-01** | High | Partially addressed: live adapter separated, but ADR-021 reuse ambiguous | **Clarified:** ADR-021's 3 operations do not supply RBAC/SAR/CSR/effective-permission evidence. A new OpenKubes-owned, capability-declared security observation contract or distinct scope-limited provider needs separate review; SAR/impersonation is not an ordinary get/list/watch tool | Before any effective-RBAC/live claim |
| **R-02** | High | Truth dimensions separated; trust-anchor choice open | **Clarified:** SHA proves bytes only; verified live outcome needs independently authenticated producer/reviewer plus tamper-evident protected record outside evaluated restore/compromise domain or equivalently justified independent trust. No such infrastructure is selected or claimed existing | Before external evidence PASS verifier |
| **R-03** | High | Disclosure mentioned; repository visibility presumed risky by Claude | **Scoped correctly:** Public source repositories are intentional; openness alone is not an incident. Treat vulnerability details and sensitive material through restricted intake, security-owner triage and authorized disclosure decision. Do not republish private tracker refs or sensitive technical details. No repo visibility change implied | Before public findings publication; review specific exposures separately when substantiated |
| **R-04** | Medium | Exact review binding already required | **Confirmed:** candidate-only advice, canonicalizer profile/version, renderer version, semantic digest and immutable reviewed transition; advisory outside the protected approval artifact | P3 E2E review confusion tests |
| **R-05** | Medium | No P0 resolver by design | **Confirmed:** bytes-only bundle; reject nonlocal references, explicitly verify no network and ambient-filesystem access in runtime isolation gate | P0 sandbox proof |
| **R-06** | Medium | Injection and redaction tests identified, without explicit exit budgets | **Strengthened:** fail-closed on unknown sensitive field, forbidden leakage and authority-shaping response; zero tolerated critical false-negative cases in a versioned adversarial fixture suite (no arbitrary general 99% accuracy claim) | Implement and execute corpus, report counts and limitations |
| **R-07** | Low | Corrected as part of SA-03 | **Confirmed:** B-06→T-42, B-14→F-18/T-32, B-15→F-23, B-18→F-26, plus full direct traceability | Independent sample/source validation |
| **R-08** | Low | Explicitly limited to declared RBAC | **Confirmed:** static observations cannot prove effective permissions; platform-control PASS needs separately authorized actual-principal evidence | Live pilot |
| **R-09** | Nit | Transport undecided | **Clarified:** OpenKubes-owned versioned schemas; a future service contract should be normative HTTP/OpenAPI when selected and MCP/CMCP optional projection; no transport selected for P0 offline function | Future live service design review |

**No Claude finding is labelled fully *verified closed*.** This matrix records draft design treatment. Runtime protection, cryptographic evidence, disclosure governance and live authorization still require explicit owners and actual proof.

## Architecture decisions retained

- **No new Policy Authority or Evidence Authority implemented in this PR.** Advisory findings cannot be redeemed for authorization or treated as admission predicates.
- **No extra RBAC in ADR-021.** Effective RBAC is not inferred from declarations, prompts or SAR alone.
- **No generic 'fail open' for protected platform mutations.** The *non-authoritative assessor* may be unavailable without blocking baseline operations; independently protected authorization itself retains fail-closed/recoverable rules.
- **No standing HOTL authority.** The proposed ADR-035 exact-HITL semantics remain the reference until a separate normative HOTL decision is accepted and independently validated.
- **No forced repository privacy change.** The user has confirmed intentional public source hosting; separately review specific disclosure risks rather than declaring an incident from visibility.

## P0 acceptance target (tiny, offline, deterministic)

1. Pinned, allowlisted **B-01** with explicit direct `F-01/F-25` and `T-01…T-04` mapping from the source-reconciled v0.2 catalog.
2. One small, synthetic, fixed-schema declared-RBAC binding example with explicit completeness; detect only the **declared** binding and possible Secret scope, never 'effective access'.
3. Reject unknown IDs, schema drift, unexpected fields, duplicate keys, traversal or external refs, oversized input, malicious text treated as instruction, and sensitive fields; fail closed on unclassifiable data.
4. Emit a structured **advisory-only** finding/evidence gap with `recorded_platform_test_outcome=NOT_RUN`, `current_applicability=UNKNOWN`, `profile_approval=NOT_APPROVED` and `severity=UNASSESSED`.
5. Execute a versioned adversarial corpus; **zero critical bypasses or secret disclosures in that bounded corpus**. Report exact tested cases, limitations and results; no platform PASS.
6. An external OS/container isolation test must enforce no network, ambient credentials, writable host paths or privileged identity before the P0 security boundary is claimed proven; unit tests alone do not suffice.

## Decisions blocked by phase

| Phase | Requires before implementation/activation |
| --- | --- |
| **P0** | Catalog and fixture owner, strict parser/output schema, test corpus, validated isolation |
| **Live P1** | A forcing consumer, scoped independent observation surface, backend principal isolation, no SAR/impersonation via ADR-021 identity, negative API/tenant/cache tests |
| **P2** | Alert owner and retention, independent control-health evidence, corroborated freshness and outage/recovery drills |
| **Live P3** | Actual trusted canonical review export and identity/transition-bound approval/claim/acceptance proof; absence of assessor causes no operational block |
| **P4** | New Accepted HOTL ADR, risk budget/revocation/acceptance/restore ordering, tested independent enforcement, separate authorized stop/recovery |

## Review and confidentiality

This review consolidation is an intentionally sanitized architecture discussion. It does not reproduce individual sensitive vulnerability exploitation instructions. Specific suspected vulnerability information should be sent through a security-maintainer-owned private intake, independently validated and released only after an explicit coordinated disclosure decision. The public repositories' visibility alone is not a security finding.

**All prior reviewed v0.1 and v0.2 documents are retained for traceability. No actual production security test has been run as part of this documentation consolidation.**
