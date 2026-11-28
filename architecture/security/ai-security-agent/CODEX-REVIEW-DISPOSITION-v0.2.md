# Codex source-based review — dispositions for AI Security Agent v0.2

**Status:** Proposed editorial/design resolutions; NOT independent acceptance or passing tests. Codex verdict on v0.1: **REVISE**. Nine issues below are addressed in draft language but remain subject to Claude review, owner acceptance and implementation tests. Codex reviewed the v0.1 source and the original CAPI ADRs; it did not test any assessor, live Kubernetes API or production profile.

| Codex ID | Severity | Disposition in v0.2 | Outstanding proof or decision |
| --- | --- | --- | --- |
| **SA-01** | High | **Addressed in design:** [Contract §1](ASSESSMENT-CONTRACT-v0alpha2.md) defines single bounded synthetic bundle, package-local IDs, no URI/network/ambient filesystem/credentials, unprivileged runtime, no LLM. | Verify actual process sandbox, parser limits and negative ambient-access fixtures in P0. |
| **SA-02** | High | **Addressed in design:** [Catalog truth dimensions](CONTROL-CATALOG-v0.2.md) and [Contract §3](ASSESSMENT-CONTRACT-v0alpha2.md) separate source classification, verification, historical test outcome, applicability and externally owned approval. | Decide producer/reviewer trust and replay/completeness requirements for later verification consumer; P0 cannot mark platform PASS. |
| **SA-03** | Medium | **Addressed in mapping draft:** one row per B-01…B-19, direct B→F/T edges extracted from Findings Register/Evidence Matrix and slash-expanded; gate dependencies separated. Corrected Role-only fixture and T-21 DockerMachine caveat. | Independent source-side check; decide whether to issue Discovery T-21 profile erratum. |
| **SA-04** | High | **Addressed in future boundary:** [Contract §4](ASSESSMENT-CONTRACT-v0alpha2.md) requires trusted audience-bound identity, explicit authorization at every hop, typed observation classes, scoped opaque handles, no arbitrary SAR/URI or Secret queries. | No live P1 adapter until consumer, backend, effective identities, revoked cache access and tenant negative tests approved. |
| **SA-05** | High | **Addressed in design:** [Contract §5](ASSESSMENT-CONTRACT-v0alpha2.md) separates preliminary candidate advice from verified canonical review, requires exact transition/review bindings and non-redeemable references; removes `authorized_to_execute`. | Verify protected review export and complete ADR-034/035 bindings for one actual named operation in a future P3. |
| **SA-06** | High | **Addressed in design:** [Spec §4](CAPABILITY-SPEC-v0.2.md) forbids assessor-produced stop/revoke/break-glass and findings as mutation/approval/CI gate or controller-watched trigger; normal/recovery flows operate without assessor. | End-to-end outage, negative downstream-consumer and recovery tests in P2/P3. |
| **SA-07** | High | **Addressed in design:** [Contract §§3,6](ASSESSMENT-CONTRACT-v0alpha2.md) separates historical receipts, current health, monotonic current authority and trusted producer/reviewer; stale/forged/replayed/truncated evidence is not current PASS. | Select independent evidence trust mechanism, restore/compromise domain, freshness and rollback/completeness tests in later phases. |
| **SA-08** | High | **Addressed in design:** [Contract §§4,6](ASSESSMENT-CONTRACT-v0alpha2.md) requires safe projection before all outputs/telemetry; restricted finding access and owner-reviewed coordinated disclosure. Fixed P0 finding class and `UNASSESSED`. | Establish security owner, disclosure playbook and redaction/export tests before broader use. |
| **SA-09** | Medium | **Addressed in scope:** [Spec §3](CAPABILITY-SPEC-v0.2.md) begins with just one B-01 synthetic declared-RBAC test and evidence-gap report; separate contract conformance, live platform-validation and named-profile approval gates. | Implement and actually execute P0 fixtures. No P1/P3/HOTL claims based on P0 test results. |

## Additional documented corrections

- **B-03/B-04:** B-03 maps directly to F-04/F-06 and T-09/T-10/T-13; B-04 to F-06 and T-13 only.
- **B-06:** direct T-14 and T-42; unavailable wipe proof keeps a host unassignable.
- **B-07:** F-03/F-17/F-25 and T-07/T-08/T-31 are direct source-table references, not an assertion that fixes work.
- **B-08/B-09/B-10:** split; T-27 directly B-10, T-24 B-08/B-13; T-21 shared B-08/B-09 with unresolved BYOH/DockerMachine test-wording issue.
- **B-11/B-12/B-17:** distinguish restore, actual effective ownership fencing and independent evidence, and keep B-17's present lack of selected storage mechanism explicit.
- **B-13/B-14:** do not misassign T-05/T-06; T-32 is directly B-14 and a cross-gate freshness obligation.
- **B-15/B-16/B-18:** F-23 / F-19 (UNVERIFIED) / F-26 respectively; G-AGENTIC-WRITE coverage is a gate set, not a single-control direct mapping.
- The v0.1 README, catalog and contract remain in the branch for review history. **They are superseded design drafts**, not competing active contract definitions. No source Discovery tables were silently modified.

## Pending decisions

- **Claude**: independent source-based architecture review still outstanding.
- **Gemini**: access-blocked feedback collected; no independent source verification.
- **Security/control owner**: sign off the catalog and fixture schema, later producer/reviewer identity and disclosure workflow.
- **Implementation**: Phase 0 fixtures and isolation tests are NOT_RUN; all platform Discovery gates remain unchanged.

This review-disposition record itself does not establish implementation, test PASS, production authority or publication approval.
