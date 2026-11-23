# ADR-Platform-000 — Security First: Lifecycle Security by Contract

- **Status:** Accepted (architecture principles; implementation and production validation not implied)
- **Date:** 2026-11-23
- **Scope:** OpenKubes platform architecture and all supported Kubernetes lifecycle profiles
- **Intentional numbering:** `000` places security at the foundation of the architecture. It does **not** retroactively supersede existing ADRs; future decisions MUST remain consistent with this ADR or explicitly amend/supersede it through the established ADR governance process.
- **Companion discovery:** `architecture/security/discovery/v0.2/` (version-pinned discovery snapshot). The discovery files remain working requirements and evidence registers, not an independently Accepted specification.

> **Secure by Contract. Verified by Evidence. Designed for Recovery.**

## Context

OpenKubes composes upstream Kubernetes technologies across provisioning, host enrollment, upgrades, management handover, disaster recovery and deletion. Their inherited permissions and failure assumptions cannot be treated as sufficient security guarantees. The CAPI/BYOH discovery identified broad host Secret access and pathways by which install, reconciliation or restore can reinstate previously removed authority.

Security must be a lifecycle property, not a post-install feature. It must also remain operationally sustainable: controls should reduce risk without unnecessarily blocking legitimate recovery.

## Decision

**Security is a prerequisite for OpenKubes lifecycle authority, not an optional add-on.** All supported implementations and deployment profiles MUST satisfy the following architectural requirements, with implementation mechanisms and evidence scoped to the relevant operation and maturity level:

1. **Explicit identity and least privilege.** A host, agent, controller or operator receives only independently justified, bounded authority. Untrusted proposals, inherited upstream permissions and self-reported component state confer no authority or trust by themselves. In particular, a host cannot independently certify its own reset/sanitization for reassignment.
2. **Independent mutation authority.** Structural safety and authorization of a specific operation are distinct. An upgrade never implicitly authorizes replacement; high-consequence actions require independently verifiable, transition-bound authorization.
3. **Lifecycle-durable enforcement.** Security must remain effective through fresh installation, reconciliation, upgrades, rollback, teardown and recovery. Neither a default manifest nor a reconciler may silently restore a removed broad privilege.
4. **Monotonic security authority.** Revocations, consumed approvals, retired identities and superseded management ownership MUST remain effective across backup restoration. Current authoritative security facts MUST be established in an independently verifiable authority such that they **survive restoration of the protected cluster to a snapshot taken before those facts existed**. They MUST be enforced **before non-recovery access and reconciliation resume**; if freshness or completeness cannot be proved, affected authority remains quarantined or is independently invalidated. The backing mechanism remains an open engineering decision.
5. **Safe, authorized recovery.** Fail-closed controls require tested, reachable recovery paths. Emergency repair must be independently authorized, scoped and auditable; a mutable bypass label or privileged identity alone is insufficient.
6. **Single effective management owner.** Handover and disaster recovery must prove old-owner fencing at every relevant write boundary, including workload APIs, BYOH host actions and infrastructure/provider interfaces. Unverifiable or disconnected targets remain quarantined.
7. **Independent, version-bound evidence.** Admission success, execution and verified outcome are separate facts. Production approval requires positive and negative tests bound to exact component versions, rendered artifacts, identity and deployment profile. The absence, disablement or degradation of enforcement components MUST be detectable and alertable independently of those components. Material changes reopen affected evidence gates.
8. **Model-specific assurance without weakened fundamentals.** CAPI/BYOH, vCluster, KubeVirt/VNC and Hosted Control Planes have different isolation properties. Their profiles may add controls and evidence, but cannot silently waive platform-wide invariants. HITL/HOTL supervision does not replace independent policy enforcement.

## Normative references and maturity

The detailed, testable *candidate* requirements are maintained in the **Security Discovery v0.2** snapshot at `architecture/security/discovery/v0.2/`. **The referenced snapshot must be present and pinned to a reviewed Git revision before this PR is merged.** B-17 operationalizes monotonic authority; B-18 covers secret-equivalent backup protection; B-19 covers security-control detection. **Acceptance of this ADR adopts its eight governing principles, not the discovery pack as an independently accepted normative specification.** Requirement acceptance, implemented controls, E2E proof and profile production approval remain separate decisions, and no open gate is closed by this ADR.

This ADR **does not select** a new policy engine, external security store, agent credential mechanism, break-glass scheme or fencing implementation. It does not certify any model as production-ready. Implementation, E2E validation and production approval are separate gates.

## Relationship to existing decisions

This ADR **complements rather than supersedes** existing ADRs. Later ADRs MUST conform to these governing principles. A conflicting exception requires a separately reviewed ADR explicitly amending or superseding ADR-Platform-000; an implementation profile cannot silently weaken it. In particular, accepted **ADR-CAPI-003** defines the **contract** for independent management ownership, a monotonic epoch and enforceable write-boundary fencing; **ADR-CAPI-005** separates backups from ownership/audit authority; **ADR-CAPI-006/007** define the **architectural contracts** for controlled handover and cold disaster recovery. These accepted decisions do **not** constitute evidence that fencing is integrated or effective at every write boundary; that remains an open finding (F-13) and must be proven by scoped negative E2E tests. OpenKubes must reuse those contracts rather than create competing authority systems. Platform ADRs 030/031/034/035/047/048 and model-specific decisions must be cross-checked before acceptance.

## Acceptance and consequences

- Every production claim must map **requirement → enforcement point → negative test → evidence artifact → scoped approval**.
- Known P0 issues, including broad BYOH host Secret authority, unverified reset/host reuse and restore-time authority resurrection, remain explicit release blockers for affected profiles until independently verified as resolved.
- Missing or stale evidence means **not approved**, not an assumed PASS.
- Added controls must be evaluated for **safety, liveness and recoverability**, including failure of the security component itself. Missing/degraded enforcement MUST trigger detection and escalation, not silent acceptance.
- Backups and snapshots containing Secrets or authority records are **secret-equivalent assets** (B-18), with explicit encryption, access, retention and recovery-key protections.

**Status boundary:** Acceptance establishes architectural principles only. It does not authorize operational changes, infrastructure mutations or publication, and makes no claim of completed security E2E validation or production readiness.
