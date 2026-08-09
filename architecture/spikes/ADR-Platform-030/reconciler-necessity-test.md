# OK-141 Reconciler Necessity Test

**Status:** Read-only analytical checkpoint
**Mutation gate:** `NO-GO`
**Operator outcome:** A/B/C/D unclassified

Inputs:

- [Carrier feasibility assessment](carrier-feasibility-assessment.md)
- [Disposable cluster observation plan](disposable-cluster-observation-plan.md)
- [Authority and revision evidence matrix](revision-correlation.md#authority-and-revision-evidence-matrix)

## Question

> **Does this gap require a new OpenKubes-owned control loop, or only a function,
> authority, persistence mechanism, evaluator, or existing controller integration?**

This is a necessity test, not a component comparison. A persistent or continuously
available service is not automatically a lifecycle Reconciler. An allocator, evidence
store, policy service, lease system, or fencing authority may be stateful and critical
without owning Cluster lifecycle convergence.

## Terminology

For this test, an OpenKubes-owned control loop must:

1. observe a declared OpenKubes desired state and relevant actual state repeatedly;
2. detect meaningful drift after the initiating operation has ended;
3. perform corrective action rather than only report evidence;
4. retry until the OpenKubes invariant converges or exposes a terminal failure; and
5. remain the declared owner of that corrective responsibility.

A deterministic function, one-shot authorized operation, read-only evaluator,
persistence service, or integration with an existing authoritative controller does not
meet that definition merely because it runs more than once or is highly available.

## Result scale

| Result | Meaning | Required justification |
|---|---|---|
| **No** | A new OpenKubes-owned control loop is demonstrably unnecessary for this gap | Identify the sufficient function, authority, persistence mechanism, evaluator, or existing controller; show why post-operation drift correction by a new OpenKubes writer is unnecessary |
| **Unresolved** | Current evidence cannot decide necessity | Identify the missing ownership, drift, correction, or existing-controller evidence and the test that can resolve it |
| **Proven** | A new OpenKubes-owned control loop is necessary | Satisfy every necessity condition below and show why all non-reconciling and existing-controller alternatives fail |

`No` does not mean “no need was noticed.” It is an affirmative claim that the stated
invariant can be maintained without a new OpenKubes-owned control loop.

## Ten-question proof test

Every gap is evaluated with the same questions:

1. What exact OpenKubes invariant must hold?
2. What is the authoritative desired state for that invariant?
3. What meaningful drift can occur after submission?
4. Must that drift be detected continuously?
5. Must corrective action be retried until convergence?
6. Who owns the affected resources today?
7. Can an existing authoritative controller maintain the invariant?
8. Can a deterministic/stateless function or authorized operation satisfy it?
9. Does persistence/evidence suffice without corrective writes?
10. What happens to existing Clusters and future operations when the proposed
    mechanism stops?

## Threshold for Proven

`RequiresReconciler=Proven` is permitted only when all statements are evidenced:

```text
OpenKubes-specific desired state exists
AND that state can drift after submission
AND the drift matters to an OpenKubes invariant
AND drift must be detected continuously
AND corrective action must be retried until convergence
AND no existing authoritative controller owns that invariant
AND a deterministic operation or evaluator is insufficient
AND persistence or authority alone is insufficient
AND the new writer has an explicit non-overlapping ownership boundary
AND stopping the writer leaves a real convergence obligation unmet
```

Failure to prove any term results in `Unresolved` or `No`, never `Proven`.

## Gap 1 — Semantic contract canonicalization

1. **Invariant:** the same semantic contract and canonicalization profile produce the
   same revision `R`; a semantic change produces another `R`.
2. **Desired state:** immutable input bytes, schema/defaulting version, semantic-field
   projection, and canonicalization profile.
3. **Drift:** none exists in a previously produced digest; new input or a new profile
   is a new calculation, not drift in the old result.
4. **Continuous detection:** no; canonicalization is evaluated at validation and
   evidence-verification boundaries.
5. **Repeated correction:** no; invalid or ambiguous input fails closed.
6. **Current owner:** contract/tooling boundary.
7. **Existing controller:** not applicable.
8. **Deterministic mechanism:** the versioned `openkubes-contract-c14n/v1` function and
   negative-control suite are sufficient.
9. **Persistence:** retaining inputs, normalized bytes, tool/schema identities, and
   digests is sufficient after calculation.
10. **Stop behavior:** new operations cannot calculate/verify `R`; already accepted
    lifecycle state continues to reconcile under its existing controllers.

**Result:** `No`

**Reason:** this is a deterministic/versioned function with persisted evidence, not a
post-submission convergence obligation. Its implementation is still Missing, but its
absence is not Reconciler evidence.

## Gap 2 — R transport and intent-to-CAPI projection evidence

1. **Invariant:** the accepted `R` and projected desired CAPI specification remain
   explicitly correlated.
2. **Desired state:** accepted intent `R`, deterministic projected specs, and the
   projection manifest/digests for one authorized transition.
3. **Drift:** unauthorized object mutation or loss/alteration of correlation metadata.
4. **Continuous detection:** CAPI already observes desired-resource drift; correlation
   can be checked at submission, observation, and evidence-review boundaries.
5. **Repeated correction:** CAPI owns reconciliation of its objects. OpenKubes need not
   rewrite `R` continuously if admission/policy protects the projection boundary.
6. **Current owner:** the authoritative intent path owns `R`; CAPI owns lifecycle
   resources.
7. **Existing controller:** CAPI maintains the lifecycle spec; policy/admission can
   constrain unauthorized mutation.
8. **Deterministic mechanism:** an authorized projection plus a content-addressed
   projection record can bind inputs and outputs.
9. **Persistence:** the retained projection/evidence record is sufficient to prove the
   mapping; a read-only evaluator detects mismatch.
10. **Stop behavior:** new transitions cannot be projected or evidenced, but accepted
    CAPI desired state continues reconciling without the Executor.

**Result:** `No`

**Reason:** the missing projection record is configuration/evidence at the operation
boundary. A new lifecycle writer would duplicate CAPI ownership.

## Gap 3 — Durable evidence bundle

1. **Invariant:** authorization, `R`, lifecycle identities, `E`, `P`, Conditions, and
   outcome remain tamper-evident and reviewable after Executor/Cluster loss.
2. **Desired state:** evidence manifest, retention/access policy, content hashes, and
   immutable artifacts.
3. **Drift:** corruption, deletion, retention expiry, or unauthorized replacement.
4. **Continuous detection:** storage integrity/retention may be monitored, but this is
   evidence durability rather than Cluster desired-state drift.
5. **Repeated correction:** replication/retention belongs to the selected storage or
   audit system; it does not correct Cluster resources.
6. **Current owner:** external evidence/audit persistence domain, currently Missing.
7. **Existing controller:** content-addressed artifact, audit, or object-storage systems
   can own storage durability.
8. **Deterministic mechanism:** a manifest builder and verifier can produce and verify
   the bundle without lifecycle writes.
9. **Persistence:** yes; persistence is the capability required.
10. **Stop behavior:** new evidence cannot be committed or verified; already accepted
    Cluster lifecycle reconciliation continues. Operations may fail closed until
    evidence service recovery.

**Result:** `No`

**Reason:** a durable service may be necessary, but no OpenKubes Cluster control loop is
needed. Storage-level reconciliation remains owned by the persistence implementation.

## Gap 4 — Global lifecycle-writer evidence

1. **Invariant:** at most one management authority may hold lifecycle write authority;
   in steady state exactly one must hold it.
2. **Desired state:** management-plane identity, authority epoch, credential scope, and
   fencing/promotion decision.
3. **Drift:** stale credentials, unintended writer activation, or promotion without
   fencing can create competing authority.
4. **Continuous detection:** authority systems may require monitoring, leases, or
   fencing, especially during ADR-031 recovery.
5. **Repeated correction:** credential revocation/fencing may be retried, but it changes
   authority rather than reconciling Cluster desired state.
6. **Current owner:** Tier-0 management/DR authority defined by ADR-031; implementation
   remains Missing.
7. **Existing controller:** identity, lease, credential, fencing, and infrastructure
   mechanisms may carry the authority invariant; they must be evaluated by ADR-031.
8. **Deterministic mechanism:** a promotion operation can be deterministic only after an
   independent fencing proof; observation alone is insufficient.
9. **Persistence:** durable authority epoch/decision evidence is necessary but may not
   be sufficient for real fencing.
10. **Stop behavior:** promotion/failover must fail closed; healthy clusters continue
    running, while lifecycle writes may safely pause at zero active writers.

**Result:** `No` for ADR-030 lifecycle reconciliation; ADR-031 implementation remains
`Unresolved`.

**Reason:** this may require a persistent authority/fencing capability, but that is a
separate Tier-0 authority domain. Treating it as Cluster lifecycle reconciliation would
blur the ownership boundary.

## Gap 5 — Allocation authority

1. **Invariant:** endpoint/CIDR allocations are unique, owned, conflict-free, and
   released or retained according to policy.
2. **Desired state:** durable reservation bound to Cluster identity, requested pool,
   lifecycle policy, and allocation UID/revision.
3. **Drift:** duplicate claims, external use, stale reservations, pool changes, partial
   deletion, and restore can invalidate uniqueness or ownership.
4. **Continuous detection:** possibly; it depends on whether the provider/IPAM system
   guarantees uniqueness transactionally or must observe external use.
5. **Repeated correction:** possibly; allocation, conflict remediation, and release may
   need retries.
6. **Current owner:** no allocation authority was observed.
7. **Existing controller:** CAPI IPAM providers, network IPAM, provider reservation
   APIs, or another existing allocator may own the invariant.
8. **Deterministic mechanism:** static reviewed allocation can work for a bounded
   profile, but not necessarily for concurrent dynamic allocation.
9. **Persistence:** a transactional reservation store may suffice if external drift is
   impossible or independently prevented.
10. **Stop behavior:** new Cluster operations must fail closed; existing allocations
    may remain valid, while release/reuse may pause.

**Result:** `Unresolved`

**Missing evidence:** inventory and test existing IPAM/allocation authorities,
transaction/isolation behavior, external-drift model, and deletion/restore semantics.
Even if a control loop is necessary, its natural owner may be IPAM rather than
OpenKubes.

## Gap 6 — Desired enablement revision E and NetworkReady

1. **Invariant:** the selected profile's desired enablement revision `E` remains
   applied and healthy, and `NetworkReady` reflects the current `E`.
2. **Desired state:** enablement profile/root linked to `R`, CNI version/config/image
   identity, ownership set, and required readiness signals.
3. **Drift:** CNI resources can be altered, deleted, partially rolled out, degraded, or
   left on a previous revision.
4. **Continuous detection:** yes; post-bootstrap networking must remain healthy.
5. **Repeated correction:** yes; the owner of CNI desired state must retry apply/upgrade
   and converge or expose failure.
6. **Current owner:** no durable Enablement root was observed; current Cilium runtime
   signals are observable.
7. **Existing controller:** CAPI add-on providers, Helm controllers, management-driven
   GitOps, or another existing add-on controller may own `E` and convergence.
8. **Deterministic mechanism:** deterministic installation alone is insufficient for
   ongoing drift, but deterministic derivation can normalize `NetworkReady` from an
   existing owner's revision-aware status.
9. **Persistence:** revision/evidence alone is insufficient if no existing controller
   maintains the desired resources.
10. **Stop behavior:** if the selected owner stops, existing networking may continue,
    but drift/upgrade remediation pauses; Executor continuity must remain irrelevant.

**Result:** `Unresolved`

**Missing evidence:** inventory and exercise existing add-on mechanisms for continuous
apply, upgrade, ownership, health, and revision semantics. Only if none can own the
profile invariant without violating boundaries can a new OpenKubes Enablement loop be
considered `Proven`.

**Potential outcome if Proven:** B when OpenKubes only composes/normalizes an existing
owner; C only when OpenKubes must own a unique enablement desired state and corrective
convergence that no existing controller can maintain.

## Gap 7 — Desired/applied platform revision P and PlatformReady

1. **Invariant:** the platform profile revision `P` linked to `R` is applied, healthy,
   and converged.
2. **Desired state:** authoritative GitOps root, requested revision, applied revision,
   profile requirements, and health/sync contract.
3. **Drift:** live resources can diverge, Git revisions can advance, and applications
   can become degraded or out of sync.
4. **Continuous detection:** yes.
5. **Repeated correction:** yes.
6. **Current owner:** no authoritative platform/GitOps root was observed in the current
   environment.
7. **Existing controller:** GitOps controllers already own desired revision, drift
   detection, apply, retry, sync, and health.
8. **Deterministic mechanism:** OpenKubes can deterministically select/describe a
   profile and derive evidence, but one-shot apply is insufficient for platform drift.
9. **Persistence:** Git plus GitOps status supplies desired/applied persistence once a
   forcing profile exists.
10. **Stop behavior:** platform convergence pauses when GitOps stops; the Cluster
    infrastructure lifecycle remains under CAPI.

**Result:** `Unresolved`

**Missing evidence:** select a forcing GitOps profile and prove its native
requested/applied revision and health semantics. The expected resolution is `No` for a
new OpenKubes loop if the existing GitOps owner satisfies the invariant; current live
evidence is insufficient to claim that result yet.

## Gap 8 — Aggregate Conditions and lifecycle result

1. **Invariant:** consumers receive one non-conflicting, generation-correct result for
   the required source Conditions correlated to `R`.
2. **Desired state:** required-condition profile and authoritative source mapping.
3. **Drift:** source Conditions/revisions change; a persisted aggregate can become
   stale even when every source owner is correct.
4. **Continuous detection:** only if OpenKubes promises a continuously current persisted
   aggregate. Evidence-on-demand can be evaluated at operation/review boundaries.
5. **Repeated correction:** a persisted aggregate may need repeated status updates;
   a read-only evaluator only recomputes a result and never corrects source resources.
6. **Current owner:** no aggregate contract/status object exists; source controllers own
   their own Conditions.
7. **Existing controller:** source owners remain CAPI, Enablement, and GitOps. Generic
   observability or policy tooling may evaluate them without becoming lifecycle owner.
8. **Deterministic mechanism:** a fail-closed evaluator can derive the result from
   retained/current source evidence.
9. **Persistence:** operation evidence may suffice unless a product consumer requires a
   continuously queryable Kubernetes status surface.
10. **Stop behavior:** source reconciliation continues. On-demand readiness becomes
    unavailable, or a persisted aggregate becomes stale/Unknown; no source resource
    should be rewritten by the aggregator.

**Result:** `Unresolved`

**Missing evidence:** decide the forcing consumer and freshness contract. If on-demand
evaluation suffices, the result becomes `No`. If a continuously current persisted
surface is required, a small OpenKubes-owned aggregation loop may be `Proven` as a B
outcome, but it must not own or remediate Cluster lifecycle resources.

## Result summary

| Gap | Result | Sufficient/non-sufficient mechanism | A/B/C/D significance |
|---|---|---|---|
| Canonicalization | **No** | deterministic versioned function plus retained inputs/digests | A-compatible |
| R transport/projection evidence | **No** | authorized deterministic projection, policy, CAPI, evidence evaluator | A-compatible |
| Durable evidence | **No** | persistence/audit capability plus deterministic verifier | A-compatible |
| Global writer evidence | **No for ADR-030** | ADR-031 authority/fencing domain; zero writers is safe during transition | Does not justify C |
| Allocation authority | **Unresolved** | existing IPAM/allocator versus bounded/static allocation not yet tested | Could remain A, or require non-lifecycle authority; C not proven |
| Enablement `E` / `NetworkReady` | **Unresolved** | existing add-on/GitOps controller candidates not yet tested | B/C boundary only after ownership proof |
| Platform `P` / `PlatformReady` | **Unresolved** | forcing GitOps root not yet observed | Expected A if GitOps owns it; not yet proven |
| Aggregate Conditions | **Unresolved** | read-only evaluator versus continuously persisted adapter | A/B boundary; not lifecycle C evidence |

```text
No          4 (one explicitly scoped to ADR-030)
Unresolved  4
Proven      0
```

> **RequiresReconciler: none proven.**

> **A/B/C/D: unclassified.**

## A/B/C/D decision gates

### A — no new OpenKubes-owned control loop

Select A only when every Unresolved gap is closed by an existing authority/controller,
deterministic function/operation, persistence capability, or read-only evaluator.

### B — bounded OpenKubes adapter, aggregation, or authority loop

Select B only when at least one gap is `Proven`, but the loop owns only OpenKubes
composition, aggregation, or authority state and never reconciles CAPI, Enablement, or
GitOps-owned lifecycle resources. B is not a smaller C.

### C — OpenKubes-specific reconciliation

Select C only when at least one gap satisfies the complete `Proven` threshold and the
new loop owns an OpenKubes-specific desired-state invariant requiring continued drift
detection and corrective convergence. The non-overlap with CAPI, Enablement, GitOps,
Policy, IPAM, and ADR-031 authority domains must be explicit.

### D — ownership duplication

Select D for a proposed solution that writes or reconciles state already owned by CAPI,
an Enablement/add-on controller, GitOps, Policy, IPAM, or the ADR-031 authority domain.
Rejecting that proposal does not imply that the original gap requires no solution.

## Next evidence required

The remaining read-only resolution work is bounded:

1. inventory and test existing allocation/IPAM authority candidates;
2. inventory and test existing add-on mechanisms for desired `E`, continuous
   convergence, upgrade, and revision-aware health;
3. select one forcing GitOps root and map requested/applied `P` plus health;
4. identify the forcing consumer and freshness contract for aggregate Conditions; and
5. keep ADR-031 authority/fencing implementation evidence separate from ADR-030
   lifecycle ownership.

No infrastructure mutation, public API, Operator scaffold, or component selection is
authorized by this test.

**Infrastructure mutation:** `NO-GO`
