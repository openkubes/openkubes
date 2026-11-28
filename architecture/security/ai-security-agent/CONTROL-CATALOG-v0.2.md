# AI Security Agent — Source-Reconciled Control Catalog v0.2

**Research draft — NOT an Accepted control standard, a test execution, a vulnerability disclosure, or production certification.**

The 19 rows below are mapped against the actual checked-in **Security Discovery v0.2** tables, rather than inferred from prose. Each B control has exactly one row. **Direct F relationships** come only from the Findings Register's *Baseline* column; **direct T relationships** come only from the Evidence Matrix's *Related baseline / finding* column. Slash shorthand such as `B-03/04` is expanded to two IDs. Discovery authors own the source register; mappings here are a pinned indexing projection, not a new authority.

## Direct source mappings (one row per B)

| Candidate control | Capability | Abbreviated source objective | Direct finding IDs | Direct test IDs |
| --- | --- | --- | --- | --- |
| **B-01** | SEC-CAP-01 | Every principal has an identifiable scope; a host credential grants no unrelated host, namespace, cluster or management-plane authority. | F-01, F-25 | T-01, T-02, T-03, T-04 |
| **B-02** | SEC-CAP-02 | Upstream RBAC and installers are reviewed under OpenKubes' threat model. Default, fresh, reinstall, upgrade, rollback and restore paths converge to **the s… | F-01, F-02, F-25 | T-03, T-05, T-06 |
| **B-03** | SEC-CAP-01/04 | Host enrollment binds independent inventory ownership, one approved host identity, the expected CSR/key and placement eligibility. A self-asserted hostname… | F-04, F-06 | T-09, T-10, T-13 |
| **B-04** | SEC-CAP-04 | Privileged host assignment is operator-controlled. A host may report operational state, but cannot self-select a control-plane or other elevated Machine as… | F-06 | T-13 |
| **B-05** | SEC-CAP-01/05 | Credential delivery, authentication, authorization and **effective revocation** are separate controls; suspension survives reconciliation and same-name ree… | F-05, F-08, F-09, F-10, F-21, F-22 | T-11, T-12, T-17, T-18, T-19 |
| **B-06** | SEC-CAP-04 | An agent's self-reported reset does not alone prove host sanitization. (a) A host with independently verified reset or trusted reprovisioning MAY be eligib… | F-07 | T-14, T-42 |
| **B-07** | SEC-CAP-01/02 | A compromised authorized controller remains bounded by structural admission and its own least-privilege identity. Controller credentials, CSR issuance righ… | F-03, F-17 | T-07, T-08, T-31 |
| **B-08** | SEC-CAP-04 | A protected Machine's creation/deletion/replacement, identity change and unauthorized spec/status transition are denied at the relevant enforcement points,… | F-11, F-12, F-14, F-15 | T-20, T-21, T-22, T-24, T-28 |
| **B-09** | SEC-CAP-03/04 | Safety constraints and authorization of an operation are distinct. High-consequence transitions require independently issued, target/transition-bound autho… | F-11, F-14, F-15, F-20 | T-16, T-21, T-28, T-29, T-34 |
| **B-10** | SEC-CAP-05 | Emergency repair is explicitly authorized, scoped and auditable. Fail-closed enforcement must have a tested recovery path reachable under the documented fa… | F-12 | T-22, T-23, T-27 |
| **B-11** | SEC-CAP-05 | Recovery does not revive old authority: post-snapshot revocations, consumed grants, revoked host generations and superseded management ownership must be re… | F-08, F-20, F-24 | T-06, T-15, T-16, T-29, T-34, T-36, T-37 |
| **B-12** | SEC-CAP-05 | Handover admits **one effective writer** at all actual write boundaries (workload API, host/agent execution, BMC, provider, SSH). An offline/partitioned ta… | F-13 | T-25, T-26 |
| **B-13** | SEC-CAP-02 | Artifact, admission-policy and enforcement-administrator integrity are protected. Routine controllers/installers cannot remove their own constraints or sil… | F-16 | T-23, T-24, T-30 |
| **B-14** | SEC-CAP-06 | Security assurance is tied to exact implementation versions, manifests, environment and negative tests; material dependency changes trigger targeted eviden… | F-18, F-24 | T-32, T-36 |
| **B-15** | SEC-CAP-06 | Model-specific profiles may strengthen or substantiate common controls, never silently waive them. Controls for models without proof remain explicitly unva… | F-23 | T-35 |
| **B-16** | SEC-CAP-03 | Agentic operations cannot mint their own authority. HITL/HOTL changes oversight, not independent enforcement; sensitive agentic write enablement requires s… | F-19 | T-33 |
| **B-17** | SEC-CAP-05 | **Monotonic Security Authority:** Security facts including revoked host identities and grants, consumed single-use approvals, retired enrollment generation… | None directly indexed | T-15, T-37 |
| **B-18** | SEC-CAP-05 | **Secret-equivalent Backup Protection:** etcd, Velero and other state backups containing Secrets, bootstrap material or authorization records MUST be prote… | F-26 | T-38, T-39 |
| **B-19** | SEC-CAP-02/06 | **Security-Control Detection:** Production profiles MUST detect and alert on disabled, missing, degraded or unexpectedly changed enforcement components and… | F-27 | T-40, T-41 |

The abbreviated objectives are for navigation only; **full normative candidate language lives in** [01-security-baseline.md](../discovery/v0.2/01-security-baseline.md). Every direct link must be reviewed against the full row's operation/profile semantics before it becomes a test oracle. `None directly indexed` is a traceability gap, not proof that a control needs no tests.

## Gate dependencies: deliberately separate from direct mapping

- **G-BYOH-ENROLL:** T-01…14, T-17, T-19, T-31, T-42 (see source Gate-to-test matrix).
- **G-UPGRADE:** T-20…24, T-27…29, T-34, T-38/39. T-27 belongs directly to B-10, **not** simply to B-09. T-24 directly maps to B-08/B-13. T-21's `DockerMachine` wording needs a profile-specific BYOH interpretation or Discovery erratum before it becomes a real-BYOH acceptance oracle.
- **G-DR:** T-06, T-15/16, T-18, T-23, T-25…27, T-36…39, T-42. A backup receipt is not a current owner epoch or revocation fact.
- **G-AGENTIC-WRITE:** T-29/30, T-32…34, T-36/37, T-40/41. These tests are **gate dependencies**; they are not all direct B-16 associations. The directly indexed B-16 finding F-19 is **UNVERIFIED**, not a reproduced exploit.
- **G-MODEL-{VCLUSTER,VNC,HCP}:** T-35 and applicable common tests; no BYOH proof inheritance.
- **Global:** T-32 evidence freshness and T-40/41 detection apply where relevant even if they are not directly indexed against an individual B row.

These lists are planning pointers, not test results. See [Evidence Matrix §2](../discovery/v0.2/03-evidence-matrix.md) for exact gate applicability and exit conditions.

## Required catalog record fields (design, not implemented schema)

`control_id`, `statement`, `source_repository`, `source_revision`, `source_path`, `source_status`, `profile`, `scope`, `capability_domain`, `enforcement_owner`, `direct_finding_ids`, `direct_test_ids`, `gate_dependency_ids`, `mapping_completeness`, `candidate_test_oracle`, `evidence_refs`, `reviewer` and `last_catalog_review`.

A model cannot create, reclassify, remove or upgrade source IDs or mappings. Unknown B/F/T references and any mismatch with the pinned catalog fail schema validation. All changed mappings require a reviewed diff against the actual source tables.

## Separate truth dimensions — never collapse into a single PASS

| Dimension | Allowed proposed values | What it actually means |
| --- | --- | --- |
| **Source classification** | `SOURCE_CONFIRMED`, `REPORTED_LAB`, `DESIGN_RISK`, `UNVERIFIED` | Basis of the source's *claim*. F-01 has separate source-observation and previously reported-lab support; neither equals an independent reproduction |
| **Verification disposition** | `UNREVIEWED`, `SOURCE_LINK_CHECKED`, `INDEPENDENTLY_VERIFIED`, `REJECTED` | Whether an identified verifier accepted the record's origin and binding; not a control health claim |
| **Recorded test outcome** | `NOT_RUN`, `PASS`, `FAIL`, `INDETERMINATE` | Historical run result. P0 cannot issue a *platform-control PASS* |
| **Current applicability** | `UNKNOWN`, `APPLICABLE`, `STALE`, `CONTRADICTED` | Whether a past observation still applies to the named current target and dependencies |
| **Deployment maturity** | `PROPOSED`, `SOURCE_COMMITTED`, `UNIT_TESTED`, `ISOLATED_E2E`, `REAL_HOST_E2E`, `PRODUCTION_APPROVED_PROFILE` | Profile-specific lifecycle, not implied by an Accepted architecture principle |
| **Profile approval** | `NOT_APPROVED`, `SCOPED_APPROVAL` | A decision from its own trusted owner, never asserted by the assessor |

A SHA-256 digest identifies bytes but is not a signature, authorized reviewer statement or live-authority fact. Historical signed receipts, dynamic health observations and **current monotonic security authority** must be independently evaluated; restoring old snapshots must not resurrect authority merely because evidence survives. If provenance, current target match, sequence completeness or reviewer authorization is missing, return `INSUFFICIENT_EVIDENCE` or `REJECTED`, not an inferred PASS.

## Minimal deterministic P0 catalog fixture

P0 starts with **B-01 only**, on a small synthetic declared-RBAC fixture containing a Role/ClusterRole and a **RoleBinding or ClusterRoleBinding**. A Role alone does not grant permissions. The evaluator may report *declared binding coverage or risk*, but **effective access** remains unknown without a complete authorization graph and (for live confirmation) results from the actual authenticated principal. Include a deliberately incomplete binding inventory and return `INSUFFICIENT_EVIDENCE`; never infer that absence from an incomplete snapshot means denied access.

Tests: exact catalog ID, direct B-01→F/T indexing, stable deterministic output, changed source SHA, missing bindings, duplicate YAML keys, secret-bearing fields, injected instructions and an explicitly NOT_RUN platform-control result.

**Implementation and source status:** Catalog generation is a proposed data processing model; this document itself is curated Research, not generated proof. No assessor software has been run.
