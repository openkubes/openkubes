# ADR-034-SP-001 — Same-Plane Authority & Executor Profile

**Status:** Proposed — design for review, NOT an activated Authority Profile  
**Date:** 2026-11-12  
**Extends:** [ADR-Platform-034](ADR-Platform-034-ok-up.md)  
**Related:** [Unified authoring Contract proposal](ADR-Platform-034-authoring-contract-proposal.md), [OK-226](https://kubernauts.atlassian.net/browse/OK-226), [OK-147](https://kubernauts.atlassian.net/browse/OK-147), [OK-148](https://kubernauts.atlassian.net/browse/OK-148), [OK-76](https://kubernauts.atlassian.net/browse/OK-76)

## Context: the smallest safe Same-Plane path

M2b proved a bounded human-operated Talos/KubeVirt cluster provision and evidence-bound teardown using a **prepared** `ok-infra` Kubernetes cluster. Same-Plane means that the CAPI management and KubeVirt provider APIs refer to the same independently verified **host Kubernetes cluster**; it does **not** mean the workload cluster has the same API identity.

ADR-034 requires exactly one authoritative desired-state revision, independent Policy decisions, an immutable transition, a single-use claim, atomic CAS acceptance and independent convergence evidence. M2b's local operator confirmation and schema-3 teardown ledger do **not** implement these requirements.

The current OK-147 runner security boundary and test fixtures assume distinct `ok-mgmt` and `ok-infra` API authorities and an ephemeral Job on `ok-mgmt`. Its `internal/runner/KubernetesAuthorityConfig` explicitly describes **separate instances** and no reusable multi-cluster administrator credential; its fixture schema `test.openkubes.io/v1alpha3` hard-codes `managementPlane: ok-mgmt` and `providerPlane: ok-infra`. These contracts **must be deliberately adapted**, not bypassed, for a Same-Plane runtime. Existing experimental `internal/bootstrapauthority` issuer store is disconnected from CLI/runner and **is not** production-fenced: immutable ConfigMaps can still be deleted/recreated, and RBAC/admission/anti-rollback remain unproven. There is no demonstrated production-ready same-plane Authority Store today.

This ADR therefore chooses a minimal target **deployment architecture** and specifies activation blockers; it does not represent finished implementation.

## Decision proposal

### SP-1. One host plane, separated *security principals*

For the first **Same-Plane profile candidate**, use the existing prepared `ok-infra` Kubernetes cluster as **both** the CAPI management cluster and the KubeVirt/CDI/Longhorn infrastructure cluster. Provisioned Talos/KubeVirt workload clusters remain separate Kubernetes APIs.

```text
Operator: openkubes.yaml / ok plan / ok up
                    |
                    v
     independently verified Policy decision
                    |
                    v
ok-infra (same verified Kubernetes API/CA/kube-system UID)
 +-- Authority Store (one desired revision + CAS ownership)
 +-- protected transition & single-use claim stores
 +-- bounded ephemeral Executor Job
 +-- CAPI/CAPK/Talos controllers
 +-- KubeVirt/CDI/Longhorn + network provider
                    |
                    v
    independent workload cluster APIs
```

**Same endpoint is not same authorization:** Policy signer, Authority Store writer, claim writer, lifecycle submission principal, provider access, and evidence reader MUST be independent identities with exact resource/verb, namespace, audience and trust constraints. No `system:masters`, wildcard write principal, ambient kubeconfig, or secret-bearing authoring YAML. The Policy signing key cannot be held by the CLI or Executor. A shared cluster control plane is a *common failure domain*, not a justification to collapse these trust boundaries.

The first profile MUST NOT automatically launch or require a new `ok-mgmt` cluster. The existing OK-147 `ok-mgmt` Job deployment is **not** converted to Same-Plane merely by repointing its kubeconfig; a separate tested configuration is mandatory.

### SP-2. Single API-backed desired-state Authority Profile candidate

Prefer **one API-backed Authority Profile on `ok-infra`** for the first conformance implementation, rather than adding a Git-backed profile, an always-running OpenKubes Operator, or an additional management cluster at the same time.

The selected durable Authority Store must represent a keyspace scoped by **tenant/cluster identity** with exactly one desired state: `ABSENT`, canonical revision `R`, or `DESIRED_ABSENT`. The store's **only authorized mutation path** is atomic, server-enforced compare-and-swap acceptance of the full tuple:

```text
expectedRevision
targetRevision | DESIRED_ABSENT
transitionID
operation
requestDigest
executionBindingDigest P
authorizationDigest
authorityProfileIdentity
```

This ADR does **not** choose a public CRD, ConfigMap encoding, web service or schema. Before selection, prove the store's atomic CAS semantics (e.g. Kubernetes resourceVersion precondition plus admission protecting the exact writer domain), inseparable persistence of transition metadata, durable retention, verified `ALREADY_ACCEPTED`, and fail-closed `INDETERMINATE` resolution after a lost response. **Do not confuse** atomic single-use claim creation with atomic desired-state acceptance; they are separate proof obligations.

A Kubernetes object with an immutable field alone is **not** an anti-deletion, anti-recreation, anti-rollback or tenant-isolation mechanism. Protect storage with dedicated writer RBAC, admission/fencing, independent readback and retention/backup policy. The Authority Store must not be in a namespace deleted with a workload cluster or depend on a workload cluster for its own recovery. An outage of `ok-infra` pauses authority acceptance and provisioning; it MUST NOT cause fallback to another writer, cached grants, another kubeconfig or Make.

### SP-3. Independent Policy and single-use execution

`ok plan` is read-only and retrieves the **authoritative predecessor revision** with independent identity checks. `ok up` submits a proposed transition; the CLI does not sign or approve it.

Before any external mutation:

1. Validate the versioned human authoring Contract and reuse OK-147's single deterministic canonicalizer to obtain semantic desired revision **R**.
2. Pin a verified Same-Plane execution profile: exact Kubernetes API identity, supported CAPI/KubeVirt/Talos provider versions, approved network allocation strategy, immutable provider source artifacts, image digests, infrastructure capacity and tenant namespace.
3. Produce immutable execution binding digest **P** containing resolution provenance and precise target API/UID/trust identity. Network `auto` is **not** a reservation: the existing M2b Make inventory check has a shared-pool concurrency race; live automatic allocation must be serialized across all writers or independently atomically reserved before approval.
4. Derive at most one supported semantic transition from the **current authoritative desired revision**, not observed replica drift.
5. Present a human-readable plan, obtain the user confirmation where required; an independent trusted Policy authority issues a decision for the exact `R/P`, transition, predecessor, audience, expiry and single use.
6. The bounded Executor independently validates Policy, identities and point-of-use preconditions, records a **durable single-use claim** and performs atomic CAS desired-state acceptance, retaining the full immutable acceptance tuple.
7. Only after proven acceptance, submit the accepted bounded operation to existing CAPI/CAPK and provider controllers; report separately: authority accepted, submitted, reconciled, independent verified outcome, and present health.

An uncertain grant/claim/CAS/API-write stops with durable correlation and **no automatic replay, rollback or cleanup**. Resume read-only inspection when safe; a new mutation needs a fresh explicit recovery decision and authorization.

### SP-4. Ephemeral Executor Job, but no new control loop

The selected executor profile is an **ephemeral, resource-bounded Job on `ok-infra`**, with exact pinned container digest, immutable package, projected short-lived purpose-limited tokens, no automounted broad ServiceAccount, non-root/read-only root filesystem, network egress allowlist and bounded deadline.

Reuse OK-147 contract, authorization, projection, ledger, observation and evidence implementations; operator CLI mode and Job mode must not become two Contract-to-CAPI compilers. Do not run a persistent OpenKubes-owned lifecycle reconciler, create a general shell/Helm executor, run the creation Job in the target workload cluster, or transfer Policy signing credentials to the Job.

Existing Runner security checks that explicitly prohibit identical `Management` and `Infrastructure` credentials MUST remain effective: a Same-Plane endpoint can be shared, but scoped **credentials, audiences, identities and permitted resource ownership** must remain distinct. Any needed adjustment to assumptions about two distinct API endpoints requires a reviewed negative-RBAC/credential test, not a global relaxation.

### SP-5. Recovery, adoption, teardown and independently verifiable evidence

- A missing Authority revision `ABSENT` is **not proof of absent resources**. Before creating, inspect authoritative CAPI, KubeVirt and known M2b resource inventories by verified identity; an existing/unknown resource fails closed. Adoption is a separate authorized and UID-bound operation, not an implicit `CreateCluster`.
- Result evidence binds `transitionID`, original predecessor, `R`, `P`, authorization digest, server-accepted CAS tuple, submitted generation, observed source UIDs/Conditions, and immutable terminal outcome. Current health is separately dynamic and never overwrites historical success.
- Future `ok down` remains **unsupported** until an authorized `DeleteCluster -> DESIRED_ABSENT -> CONFIRMED_ABSENT` contract passes. The M2b original-UID/schema-3 storage/Golden Image/Longhorn safeguards remain intact; direct `ok cluster destroy` is a distinct expert operation.
- The Authority Store and evidence must survive target namespace deletion, failed Job execution, ephemeral credential expiry, and control-plane restarts. Document recovery when `ok-infra` itself becomes unavailable: restore only with independently verified provenance and no competing authority incarnation. No automatic local kind bootstrap or pivot is part of this M3 profile.

## Separate the three things that can be called an "authority"

| Responsibility | Owner | What it must NOT do |
| --- | --- | --- |
| Desired-state Authority | Selected `ok-infra` Authority Profile with CAS | Decide Policy or infer desired state from current health |
| Authorization/Policy Authority | Independently administered trusted Policy signer/verifier | Become a second desired-state writer or hand signer secrets to `ok`/Job |
| Kubernetes API/CAPI authority | Existing Kubernetes API and CAPI/controllers on `ok-infra` | Authorize OpenKubes desired-state changes merely because Kubernetes RBAC permits them |

**Independent Policy** means *independent trust and writer privileges*, not necessarily an additional Kubernetes control plane. The exact Policy signer trust bootstrap, operational host and recovery process require separate review; colocating its process is not enough to prove independence.

## Conformance and activation gates (all required)

1. Positive Same-Plane: management/provider **same verified API identity**, separately scoped principals; workload Kubernetes API independently identified.
2. Negative: changed CA, server endpoint, kube-system UID, credential audience, namespace UID, or mismatched provider identity causes **no mutation**.
3. Authority Profile supplies linearizable CAS, a single winner under concurrent proposals, correct stale predecessor failure, full-tuple `ALREADY_ACCEPTED`, and lost-response resolution.
4. Admission/RBAC prevents unauthorized writing, deletion/recreation, replay and rollback of Authority and claim records; simulated object deletion/recreation and namespace-fence resets fail closed.
5. Policy signer ownership, rotation, key mismatch, expired/replayed grants and absent Policy prove independently enforced STOP.
6. `R/P` is bound before any live mutation; no IP allocation race, changed renderer result, uncontrolled Make writer or post-confirmation substitution.
7. CLI and ephemeral Job share the same deterministic contract/executor code and produce identical allowed projections; no second desired-state writer.
8. Positive authorized CreateCluster and NoOp; unknown pre-existing M2b cluster, conflicting UID, stale plan and unsupported Scale/Upgrade/Delete fail closed.
9. Interruption after claim, CAS acceptance, submission and observation are separately fault-injected; no uncertain automatic retry/false success; independently inspectable durable correlation.
10. Independent evidence verifies source generation/UID, CAPI Machine/VM/workload readiness and desired/current state distinction. The source controller retains actual reconciliation ownership.
11. Least-privilege Job ServiceAccounts, credential expiry, token projection, egress policy and absence of signing keys are independently tested on a disposable Same-Plane environment.
12. Authority Store backup/restore/fence and planned disaster recovery tests show no competing Authority incarnations or unsafe automatic failover.
13. M2b schema-3 teardown evidence, unrelated Golden Images and storage remain protected; deletion is **not** enabled by completing Create tests.
14. No production activation on the basis of fake TLS API/local unit tests or a merged design PR alone; live conformance, independent security review and precise signed-binary release gates remain necessary.

## Implementation sequence

**SP.1 Architecture** — Review this ADR and map all OK-147 assumptions about distinct endpoint/credentials, ledger, claims and Job placement. Approve the single store keyspace, API-backed CAS owner and Policy trust bootstrap (still no runtime changes).

**SP.2 Store & conformance** — Implement one durable, anti-deletion-fenced desired-state Authority adapter, dedicated claim store, read-only inspection, transition metadata and full failure tests. Do not reuse `internal/bootstrapauthority` issuer store as if it were a production desired-state store.

**SP.3 Execution profile** — Prepare reviewed in-cluster `ok-infra` Job profile and distinct credentials; negative RBAC/identity/expiry tests.

**SP.4 End-to-end** — Run authorized `CreateCluster` / `NoOp` against a disposable Same-Plane environment and verify generation-correct evidence. Keep `ok up` routing unchanged until this and public input schema conformance are accepted.

**SP.5 Product migration** — Only then migrate to a single user-visible `ok up` preserving legacy behavior through explicit versioned compatibility rules; `ok down` remains separately gated.

## Consequences and limits

This avoids requiring a second management cluster for the first supported prepared-infrastructure journey and avoids shipping two independent lifecycle engines. It **does not** eliminate security boundaries, make a shared `ok-infra` control plane an independent failure domain, implement an Authority Store, prove CAS/admission safety, or make any profile publicly releasable. Split-Plane, arbitrary pre-existing Kubernetes installations and M4 local `kind` Zero-to-Cluster Bootstrap remain separate conformance scopes.

**Acceptance:** Architectural acceptance requires review with OK-147/OK-148 owners; production profile activation requires all applicable ADR-034 and SP-001 executable evidence. Keep `Status: Proposed` until that review is complete.
