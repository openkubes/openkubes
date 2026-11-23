# OpenKubes AI Security Agent — Architecture & Capability Specification v0.2

- **Status:** Research Draft — review consolidation in progress; **NOT an Accepted ADR, deployed agent, production approval or vulnerability disclosure**.
- **Date:** 2026-11-23
- **Review basis:** Source-inspected Codex review (SA-01…SA-09) of v0.1; independent Claude review still pending. Gemini access-blocked feedback is not a source-validated review.
- **Normative hierarchy:** [ADR-Platform-000](../../decisions/ADR-Platform-000-security-first.md) (Accepted principles) → other ADRs (their actual statuses) → [Security Discovery v0.2](../discovery/v0.2/README.md) (research, not accepted) → independently verified named-profile evidence.
- **Detailed companions:** [source-reconciled Control Catalog v0.2](CONTROL-CATALOG-v0.2.md), [Assessment Contract v0alpha2](ASSESSMENT-CONTRACT-v0alpha2.md), [Codex finding dispositions](CODEX-REVIEW-DISPOSITION-v0.2.md).

> **AI Security Agent = independent, non-authoritative, evidence-based advice.** The trusted platform retains all identity, human approval, policy, execution, admission, stop, fencing and recovery authority.

## 1. Purpose and maturity

The Security Agent assists operators by distinguishing *declared controls* from *actual enforcement*, *historical test outcomes* from *current applicability*, and *source claims* from *independent proof*. It may classify risks and evidence gaps, but **must never pronounce production platform controls PASS merely because an ADR, a signed receipt or a manifest exists**.

The initial CAPI/BYOH work does not imply proof for vCluster, VNC/KubeVirt or HCP. No LLM, live Kubernetes access or write credential is needed in P0.

## 2. Six independent capability domains

| ID | Domain | Examples of advisory functions | Source anchors |
| --- | --- | --- | --- |
| SEC-CAP-01 | Identity and Access | Declared/effective RBAC, credential exposure, agent/tool-server identity, scoped host enrollment | ADR-000; ADR-021 (Draft); B-01/03/05/07 |
| SEC-CAP-02 | Policy and Configuration Assurance | Admission coverage, installer/reconcile drift, control disablement/detection | ADR-000; ADR-034 (Proposed); B-02/13/19 |
| SEC-CAP-03 | Agentic Operations Security | Untrusted proposal risks, fixed-field scope, shared tool-server privilege, replay and bypass hypotheses | ADR-035/042 (Proposed), ADR-044 (Draft); B-09/16 |
| SEC-CAP-04 | Infrastructure Lifecycle | BYOH placement/reset, no-replacement, in-place upgrade, unauthorized fallback | ADR-030/047/048 (Proposed); B-03/04/06/08 |
| SEC-CAP-05 | Recovery and Authority Integrity | Ownership fencing, restored stale grants, monotonic facts, backup material and authorized recovery | ADR-000; ADR-031 (Proposed); ADR-CAPI-003/005/006/007 (Accepted architecture); B-10/11/12/17/18 |
| SEC-CAP-06 | Evidence and Assurance | Requirement → enforcement → negative test → actual run receipt → named-profile approval | ADR-000; B-14/15/19, Discovery Evidence Matrix |

The read-only assessor **is not** the independent Policy Authority and **must not** decide which changes can be applied.

## 3. Phases and independently gated deliverables

### P0 — Tiny, deterministic offline proof

**Only deliverable:** A fixed, synthetic single-bundle B-01 *declared RBAC* check and a missing-evidence report against a pinned catalog. The bundle includes explicit Role/ClusterRole, RoleBinding/ClusterRoleBinding and completeness metadata. A standalone Role alone grants nothing. An incomplete declared grant graph cannot prove absence of effective access.

P0 takes **bounded bytes and package-local IDs**, no caller-directed URLs, filesystem paths, environment variables or network lookups. It runs without LLMs, Kubernetes credentials, network, host mounts, ambient credentials or arbitrary files, under independently tested unprivileged resource isolation. Every control-level platform test remains **NOT_RUN**; P0 may pass its *own parser/conformance tests* but cannot mark a production control PASS.

**Exit:** repeatable parsing/assessment and accurate `INSUFFICIENT_EVIDENCE` on missing, ambiguous, hostile, secret-bearing or incomplete inputs; negative tests for ambient reads/network, duplicate YAML keys, incorrect B/F/T links and injection. Fixed, non-LLM finding classes; severity `UNASSESSED`.

### P1 — Offline assessment, with separately authorized optional live adapter

Extend deterministic declared-resource analysis. Only after a forcing consumer, trust model and ADR-021-compatible observation contract are reviewed may a **separate live read-only pilot** exist. Backend authorization intersects original authenticated caller, actual provider/workload identity, tenant, cluster, immutable resource, observation class and authorized recipient at every hop (including cache and delivery). No arbitrary SAR, log, URI, Secret, privileged tool-server or agent-supplied principal query.

**Exit:** offline declared-resource conformance separate from any proven real-principal read/Secret/mutation denials. Live API tests are required before live access claims; no privilege inherited through gateway or direct backend paths.

### P2 — Continuous Security Assurance

Periodically compare bounded observations and independently sourced control-health information to the pinned control policy, record **historical receipt**, **current target applicability**, **current control health** and **current security authority facts** separately. Historical receipts cannot establish that a revoked credential remains revoked after an older snapshot restore.

**Exit:** source freshness, provenance, missing-data, silent collector failure, detector outage, alert routing, recovery and non-blocking core operations tested under relevant failure modes. The assessor remains advisory and cannot become a reconciliation gate.

### P3 — AI SRE proposal advisory review

Assess either (a) an **untrusted candidate digest** for preliminary advice or (b) a trusted, immutable semantic review projection with the full canonicalizer/renderer versions, predecessor and target, transition ID, revision digests and execution-profile bindings. Never label (a) a canonical-transition assessment; old advice becomes historical when the binding changes.

**Exit:** an independently enforced approval/Policy/Executor/Authority path exists for the named operation and all identity, replay, approve-A/execute-B and lost-response negatives are demonstrated. The assessor receives **non-redeemable read-only references only**. Findings never become grant, approval, controller-watched intent, stop or break-glass commands. Operations and recovery still function with the assessor absent.

### P4 — HOTL security assurance (research-only)

Observe the evidence of a **separately approved** HOTL standing mandate and per-transition grant workflow; report missing current scope, revocation, budget, fencing or restore proof. Human governance and independent execution remain outside the Security Agent.

**Activation prerequisites:** a new accepted normative HOTL ADR reconciling ADR-035/042, a profile-specific authority ordering protocol and actual concurrency/revocation/stop/recovery/restore E2E. Finishing P0–P3 neither unlocks nor approves HOTL.

**These phases are delivery stages, not increasing agent privileges.** Live pilot, SRE integration and HOTL activation have separate decisions.

## 4. Non-authority, availability and data safety (SA-04…SA-08)

1. **No hidden gatekeeping:** Security Agent presence, absence or recommendations are **not** inputs to policy predicates, mandatory human approval, protected semantic review, mutation/rollout triggers, admission decisions, controller watches, stop/pause/revoke, break-glass or authorized recovery. Any future binding governance change would require its own accepted ADR and liveness evidence.
2. **No ambient identity:** A caller-supplied principal ID is not authentication. A future live adapter requires authenticated audience-bound delegation and backend checks at ingress, collection, caching, evidence lookup, and delivery. P0 has no live principals at all.
3. **Evidence trust dimensions:** keep source classification, verification disposition, recorded run outcome, current applicability, implementation maturity and separately owned scoped approval as distinct fields. Version/digest match is necessary but insufficient for independent origin, completeness or freshness.
4. **Separate trust domains:** historical receipts, current health and current monotonic revocation/ownership/grant facts belong to their respective independently authorized owners. No generated text or assessment result can serve as security authority.
5. **Sensitive data projection:** prevent leakage **before model use and before every output** including errors, logging, audit, caches, exports and notifications. Suppress reusable private artifact handles, secrets, endpoints and topology. Findings default to restricted access; public disclosure requires independent security-owner validation and explicit review of the rendered release artifact.
6. **No severity inflation:** P0 uses fixed finding classes and `UNASSESSED`, not LLM-based CVSS-like scoring, direct exploit declarations or PASS assumptions.

## 5. Source-accurate traceability (SA-03)

The [v0.2 Control Catalog](CONTROL-CATALOG-v0.2.md) contains **exactly one row for B-01 through B-19**, whose direct F and T links are derived from the source's respective mapping columns, including slash expansions such as `B-03/04`. **Gate dependencies are in a separate section** and must not be mislabelled direct evidence.

Codex highlighted a test-wording caveat: Discovery T-21 mentions `DockerMachine` despite BYOH framing. It must be interpreted by named profile or corrected in Discovery after a separate source review, not silently used as a BYOH proof oracle. Real-host evidence remains unproven.

## 6. Minimal Phase-0 example

Synthetic binding granting a declared host service identity excessive access is a **declared-RBAC concern**, not a demonstrated live compromise. The evaluator reports: identified binding and scope, B-01 direct source references, exact missing inventory, `NOT_RUN` platform test, `UNKNOWN` current applicability and `UNASSESSED` severity. No imperative script, policy change, approval or authority-shaped response is emitted.

The [v0alpha2 contract](ASSESSMENT-CONTRACT-v0alpha2.md) defines an illustrative fixed input/output and separate future read-only and SRE interfaces. It does not expose a callable API.

## 7. Security-review and implementation gates

- **G0 — Review:** verify the nine Codex findings are substantively resolved in v0.2; obtain Claude's independently sourced review. Gemini's inaccessible-source BLOCK is not a validation of the source-based draft.
- **G1 — P0 contract:** approve pinned catalog and fixture owner, define one deterministic evaluator/format, build and execute negative fixtures. No cluster or external source access.
- **G2 — Future integration:** authorize each P1/P2/P3 consumer and read-only observation class separately; preserve existing diagnostics and privilege boundaries.
- **G3 — HOTL:** separate new accepted ADR and full enforcement/evidence tests. No standing mandate is authorized here.

**No website edits, new tickets, deployment, merge or production change is authorized by this research draft.** No actual platform-control PASS has been claimed or tested in this update.
