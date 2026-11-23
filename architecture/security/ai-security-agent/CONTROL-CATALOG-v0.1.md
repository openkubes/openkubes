# AI Security Agent — Control Catalog Seed v0.1

**Status:** Research seed only; not a normative specification or a completed control assessment. The exact source of truth for B-/F-/T-identifiers is [Security Discovery v0.2](../discovery/v0.2/README.md). **ADR-Platform-000 is Accepted at the principle level**; its companion discovery is not. Every proposed mapping below must be revalidated against the cited pinned sources and test definitions before implementation or publication.

## Catalog record contract

Each control must identify: `control_id`, `statement`, `source_path`, `source_revision`, `source_status`, `control_domain`, `scope`, `enforcement_owner`, `observable_evidence`, `negative_test_ids`, `finding_ids`, `evidence_status` and `last_verified_at`. A catalog assertion is **not** proof a control is enforced. Unknown ownership, test artifacts or freshness must be `UNVERIFIED` or `NOT_RUN`, not an inferred PASS.

## Curated seed mapping (illustrative, not exhaustive)

| Discovery control | Capability domain | Source-defined safety objective | Relevant finding(s) | Representative test(s) and proof obligation |
| --- | --- | --- | --- | --- |
| **B-01** | SEC-CAP-01 | Principal scoped to own identity, host, namespace and cluster | F-01 | T-01…T-04: own named Secret read permitted, peer/foreign/management and list/watch denied |
| **B-02** | SEC-CAP-02 | No unsafe broad-grant reintroduction on install/reconcile/rollback | F-02 | T-05/T-06: fresh, reinstall, rollback and continuous authorization samples |
| **B-03/B-04** | SEC-CAP-01/04 | Inventory-bound enrollment and non-agent-controlled privileged placement | F-04/F-06 | T-09/T-10/T-13: wrong CSR/token/selector denied; authorized host works |
| **B-05** | SEC-CAP-01/05 | Effective durable credential revocation and enrollment generations | F-05/F-09/F-10 | T-11/T-12/T-17/T-18/T-19: restart/re-enroll/replay and delivered-material checks |
| **B-06** | SEC-CAP-04 | Self-reported host reset cannot prove sanitation for reassignment | F-07 | T-14: adversarial false-reset must not release host |
| **B-07** | SEC-CAP-01/02 | BYOH controller Secret/CSR/infrastructure power is least-privileged | F-03 | T-07/T-08: effective controller denials plus permitted reconciliation |
| **B-08/B-09** | SEC-CAP-03/04 | Upgrade is not replacement; exact, independently authorized transitions | F-11/F-14 | T-20…T-22/T-27: protected real-host upgrade, forbidden fallback and recovery |
| **B-10** | SEC-CAP-05 | Deny unauthorized mutation without preventing tested authorized recovery | F-12 | T-23/T-24: enforcement-outage and recovery route exercises |
| **B-11/B-17** | SEC-CAP-05 | Restore must not resurrect revoked/superseded authority | F-08 | T-15/T-16/T-37: pre-revocation snapshot and current monotonic facts |
| **B-12** | SEC-CAP-05 | Single effective writer across actual workload/host/provider write points | F-13 | T-25/T-26: old-owner writes denied, partitioned/offline targets quarantined |
| **B-13/B-14** | SEC-CAP-02/06 | Control integrity, artifact/version-bound evidence and freshness | F-02/F-12 | T-05/T-06/T-32: reconcile and material-update invalidation |
| **B-15** | SEC-CAP-06 | Model-specific evidence; no transfer of BYOH proof to vCluster/VNC/HCP | Profile dependent | T-35 + applicable common tests: model-scoped review |
| **B-16** | SEC-CAP-03 | Agent never mints its own mutation authority; HITL/HOTL distinct from policy | Agentic design risks | G-AGENTIC-WRITE: T-29/30, T-32…34, T-36/37, T-40/41 |
| **B-18** | SEC-CAP-05/06 | Backup artifacts and restoration material protected as secret-equivalent | Discovery crosswalk | T-38/T-39: backup access/encryption/key recovery and restore controls |
| **B-19** | SEC-CAP-02/06 | Detection of missing/degraded enforcement and selected denied boundary attempts | F-27 | T-40/T-41: independent detection, alert and retention evidence |

**Provenance caveat:** The finding/test associations are a planning index to the snapshot, not independent confirmation that those tests succeeded. Source-only conclusions, reported prior labs, design reasoning and unverified behavior must remain separately labeled. Exact many-to-many coverage (including tests not shown) is owned by the Discovery Evidence Matrix, not this simplified seed.

## Confidence, evidence and maturity — three orthogonal fields

| Dimension | Allowed vocabulary | Interpretation |
| --- | --- | --- |
| Finding provenance/confidence | `SOURCE_CONFIRMED`, `REPORTED_LAB`, `DESIGN_RISK`, `UNVERIFIED` | Classification of what the source justifies; does not mean exploitation or severity |
| Test outcome | `NOT_RUN`, `PASS`, `FAIL`, `INDETERMINATE` | Only a version-bound, actual run can justify PASS/FAIL |
| Implementation maturity | `PROPOSED`, `SOURCE_COMMITTED`, `UNIT_TESTED`, `ISOLATED_E2E`, `REAL_HOST_E2E`, `PRODUCTION_APPROVED_PROFILE` | Progressive profile-specific proofs; a source review or Accepted ADR does not qualify as a later stage |

An assessment must separately return `reviewed_source_revision`, `observed_target_revision`, `evidence_timestamp`, `confidence`, `test_outcome` and `maturity`. An absent artifact, mismatched target, unknown revision or stale evidence is an **evidence gap**, not a passed control.

## Phase 0 verification fixtures

- **Positive:** Valid catalog row resolves to a real source ID and recorded status.
- **Negative:** Unknown or misspelled B/F/T identifier, missing source SHA, false PASS without execution artifact, stale manifest revision, and mismatched tenant/namespace are rejected or marked indeterminate.
- **Adversarial:** A malicious Markdown/manifest comment requests the assessor to disable validation or approve an operation; output remains a data finding and the instruction is ignored.
- **Privacy:** Fixture with token-like text, client certificates, Secret `data` and kubeconfig fields is redacted before any optional model interaction.

## Maintainer rule

Changes to this seed require source pointers and independent evidence review. The Security Agent must never silently change these mappings or their normative maturity based on a generated answer.
