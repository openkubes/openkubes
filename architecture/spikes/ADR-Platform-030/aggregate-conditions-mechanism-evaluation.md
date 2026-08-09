# Aggregate Conditions Mechanism Evaluation

Status: **Read-only mechanism evaluation; no status API or controller selected**

Recorded: 2026-08-09

Branch: `spike/OK-141-aggregate-conditions`

Baseline: `main` at `117bfb4`

## Question

Can OpenKubes derive one generation- and revision-correct lifecycle outcome with a
bounded read-only evaluator, or does a concrete product consumer require a continuously
published OpenKubes status surface?

This evaluation is limited to aggregation. It does not authorize:

- a public `OpenKubesCluster` API;
- an OpenKubes Operator or status controller;
- writes to CAPI, Enablement, GitOps, or workload resources;
- installation or reuse of a GitOps control plane;
- infrastructure mutation; or
- failure injection.

The current mutation and failure-injection decision remains **NO-GO**.

## Inputs and evidence boundary

This document evaluates the existing OK-141 evidence:

- [Condition source map](condition-source-map.md);
- [Authority and revision correlation](revision-correlation.md);
- [Disposable-cluster observation plan](disposable-cluster-observation-plan.md);
- [Reconciler necessity test](reconciler-necessity-test.md);
- [Allocation Authority mechanism evaluation](allocation-authority-mechanism-evaluation.md);
- [Enablement E and NetworkReady mechanism evaluation](enablement-network-ready-mechanism-evaluation.md); and
- [Platform P and PlatformReady mechanism evaluation](platform-ready-mechanism-evaluation.md).

No live infrastructure was queried for this follow-up. Repository searches found
architecture statements and component-specific readiness checks, but no implemented
OpenKubes consumer that watches or requires a continuously published aggregate
`Ready` Condition. In particular, no implemented `ok cluster status`, `ok cluster
wait`, policy dependency, or external controller consuming an OpenKubes aggregate
status was found.

Absence in the reviewed repository is not proof that no future consumer will exist. It
does mean that such a future consumer cannot justify a persistent writer today.

## Ownership invariant

Aggregation must preserve the authority of every source domain:

```text
CAPI             -> infrastructure and Cluster lifecycle facts
Enablement owner -> desired E, convergence, and network facts
GitOps owner     -> desired/applied P, convergence, and platform facts
Allocator/IPAM   -> allocation identity and validity, where required

OpenKubes evaluator
  -> observe
  -> correlate
  -> normalize
  -> derive an outcome
  -> never repair a source resource
```

An aggregate `False` or `Unknown` result must not cause the evaluator or a possible
future status adapter to apply, patch, restart, prune, or otherwise remediate a CAPI,
Enablement, GitOps, allocator, or workload resource.

### Relationship to proposed ADR-030

ADR-030 currently names exactly one OpenKubes Status Aggregator and makes its
single-writer behavior an acceptance condition. Because ADR-030 remains `Proposed` and
the spike is intended to discover required components, that component statement is a
hypothesis under test rather than implementation authorization.

If the bounded-evaluator result survives review and execution evidence, ADR-030 must
be adjusted before `Accepted` so that it requires one deterministic aggregate result
and unambiguous source ownership without requiring a continuously running status
writer. If a later forcing consumer proves Model B necessary, the single-writer rule
continues to apply to that adapter's normalized status surface.

## Source Condition inventory

The inventory distinguishes a source authority from an OpenKubes-normalized name. A
normalized name is a derived view; it does not transfer source ownership to
OpenKubes.

| Normalized fact | Authoritative source | Required identity/revision correlation | Freshness requirement | Current mechanism assessment |
|---|---|---|---|---|
| `InfrastructureReady` | CAPI Cluster `InfrastructureReady`, derived from the selected InfraCluster provider | CAPI Cluster UID/spec is linked to intent `R`; InfraCluster identity is linked through typed references/owner relationships | Required CAPI and provider objects have observed their own current generations | Existing source sufficient in principle; disposable proof pending |
| `ControlPlaneAvailable` | CAPI Cluster `ControlPlaneAvailable`, derived from the selected ControlPlane provider | CAPI Cluster and ControlPlane identities are linked to the projection of `R` | Current object-local generations are observed; historical initialization is not ongoing availability | Existing source sufficient in principle; use v1beta2 `Available` semantics rather than freezing the historical `ControlPlaneReady` name |
| `WorkersAvailable` / machine facts | CAPI Cluster, MachineDeployment/MachineSet, and Machine Conditions | Current Machine graph belongs to the CAPI Cluster projection for `R` | Every required scalable resource and Machine observation is current | Existing CAPI mechanism sufficient in principle |
| `NetworkReady` | Selected Enablement owner plus workload Node/Cilium sources and profile-defined functional probes | Desired semantic Enablement revision `E` is linked to `R`; observed resources resolve to the same `E` | Controller-owned desired/applied state, object generations, rollout state, Node state, and probe evidence are current | E construction is deterministic; convergence configurable; normalized publication unresolved |
| `EnablementReady` | Selected Enablement root and the complete profile-required enablement capability set | Exact required capability set and its revisions are linked to `E` and `R` | Every required capability has current authoritative evidence | No single current OpenKubes source; derivation is plausible after an Enablement root is selected |
| `PlatformReady` | Selected GitOps profile root/Application set plus profile-defined capability checks | Desired and applied immutable platform revision `P` are equal and linked to `R` | Current comparison, sync, health, and required capability checks all refer to `P` | P construction deterministic; GitOps convergence configurable; read-only evaluation plausible |
| Allocation validity, when profile-required | Declared allocator/IPAM authority or reviewed static/bounded allocation contract | Current allocation UID/revision belongs to the target Cluster identity and `R` | Allocation has not expired, been superseded, or been assigned concurrently | Endpoint allocation covered by existing mechanisms; fixed provenance configurable; Pod/Service CIDR authority unresolved |
| Management writer authority, when operation-required | Independent authority/fencing evidence defined by ADR-031 | Active management identity/epoch matches the lifecycle projection | Evidence proves at most one writer; API unreachability alone is insufficient | Not an aggregate lifecycle reconciler concern; ADR-031 remains separate |

The aggregate evaluator must consume these authorities. It must not replace them with
name equality, matching IP addresses, timestamps, process exit, or a previous
successful operation.

## Required-condition profile

`Ready` cannot have one universal input set independent of a profile. The evaluator
must receive an immutable required-condition profile that declares:

- profile identity and version/digest;
- the normalized Conditions required for `Ready`;
- optional Conditions that are reported but do not gate `Ready`;
- exact authoritative source kinds and relationships;
- the revision carrier for `R`, `E`, and `P` where applicable;
- freshness rules for each source type;
- profile-defined functional probes; and
- evaluator policy version.

The profile is evaluator input, not a hidden default. Changing required membership or
evaluation semantics changes the profile identity and invalidates a result evaluated
under the previous profile.

## Evaluation model

### Source evaluation

Each required normalized Condition is evaluated independently as `True`, `False`, or
`Unknown`.

| Situation | Normalized result | Rule |
|---|---|---|
| Authoritative source is current, correlated to the required revision, and reports success | `True` | All source-specific positive assertions must pass |
| Authoritative source is current, correlated, and reports a current failure | `False` | Preserve the source `reason` and causal detail |
| Required source or observer is missing/unreachable | `Unknown` | Missing evidence is never success and is not automatically an authoritative failure |
| Source observation belongs to an older object generation | `Unknown` | Stale success or failure cannot describe the current desired state |
| Desired/applied `R`, `E`, or `P` cannot be correlated exactly | `Unknown` | Similar names, versions, values, or timestamps never establish correlation |
| A historical success exists but the current comparison fails | `Unknown` or `False` from the current authoritative source | Historical operation state never overrides current evidence |
| Authoritative source reports failure while supporting runtime evidence looks healthy | `False` | Supporting observations do not override the authority |
| Two alleged authoritative sources conflict | `Unknown` plus `ConflictingAuthority` | The ownership contract is invalid or incomplete; the evaluator must not choose a winner |
| Optional Condition is missing or failing | Its own `Unknown` or `False`; does not gate `Ready` | Optionality affects only aggregate membership, not the truth of the optional fact |

Where a source exposes no Kubernetes `observedGeneration`, its mechanism-specific
freshness contract must prove an equivalent relationship. For example, a GitOps
evaluation may require normalized current desired source, current comparison state,
exact applied revision vector, sync status, health, and absence of current comparison
errors. The evaluator must not invent `observedGeneration` for such a source.

### Aggregate evaluation

For the immutable required-condition profile:

```text
if any required Condition == False:
    Ready = False
else if any required Condition == Unknown:
    Ready = Unknown
else if every required Condition == True:
    Ready = True
else:
    Ready = Unknown
```

This gives current authoritative failure precedence over missing evidence while still
ensuring that `Ready=True` requires complete proof.

An evaluator result must include:

- `R` and the required-condition profile identity;
- referenced `E`, `P`, and allocation/authority identities when required;
- every normalized source result with source UID, revision/generation, status,
  reason, message, and observation time where available;
- the aggregate result and deterministic reason;
- evaluator version/tool digest;
- evaluation time;
- exact input artifact hashes; and
- evidence-bundle checksum when retained.

Successful Executor or evaluator exit is not itself lifecycle success. The result is
`Ready=True` only when the evaluated evidence says so.

### Reason rules

Candidate deterministic aggregate Reasons are:

| Result | Reason | Meaning |
|---|---|---|
| `True` | `AllRequiredConditionsSatisfied` | Every required source is current, correlated, and `True` |
| `False` | `RequiredConditionFailed` | At least one current, correlated authoritative source is `False` |
| `Unknown` | `RequiredEvidenceMissing` | A required source or artifact is absent |
| `Unknown` | `SourceObservationStale` | A required observation does not describe the current generation/revision |
| `Unknown` | `RevisionCorrelationUnproven` | `R`, `E`, `P`, or source identity cannot be correlated |
| `Unknown` | `ObserverUnavailable` | Current truth cannot be obtained from a required failure domain |
| `Unknown` | `ConflictingAuthority` | More than one alleged authority provides incompatible facts |
| `Unknown` | `EvaluationProfileInvalid` | Required membership or source mapping is ambiguous/invalid |

When several conditions fail, the result must retain the complete ordered cause set.
A single headline Reason must not discard source Reasons and messages.

## Staleness and time

Generation correctness is preferred over elapsed-time heuristics:

```text
object generation correlation
    > exact semantic revision correlation
    > source-specific comparison identity
    > wall-clock freshness alone
```

A time-to-live may be part of a functional-probe contract, credential check, allocation
lease, or evidence-retention policy. It must not be used as a substitute for object or
revision correlation.

The bounded evaluator reports `evaluatedAt`. It cannot truthfully publish Kubernetes
`lastTransitionTime` without retained prior aggregate state. A future persistent
status adapter could maintain `lastTransitionTime`, but that capability is not needed
for a bounded operation/evidence result and does not by itself justify the adapter.

## Negative controls

The mechanism is acceptable only if fixtures prove that each of the following cannot
produce `Ready=True`:

1. one required source is absent;
2. one required observer is unavailable;
3. a CAPI source has stale `observedGeneration`;
4. a source object has the expected name but a foreign UID;
5. `R` differs from the projected CAPI intent revision;
6. runtime network health belongs to a different `E`;
7. GitOps is healthy for a different or unresolved `P`;
8. GitOps has historical successful operation state but a current comparison error;
9. a required profile member is missing while all remaining members are healthy;
10. an optional member is missing (the optional fact is not `True`, but aggregate
    `Ready` remains governed only by required members);
11. two alleged authorities provide conflicting evidence;
12. one retained artifact hash has changed;
13. the Executor exited successfully without complete source evidence; and
14. a prior `Ready=True` result is replayed against a newer `R` or profile identity.

## Consumer inventory

A continuously published aggregate needs a forcing consumer. Convenience, anticipated
future use, or a box in ADR-030 is insufficient.

| Consumer | Needs continuously persisted aggregate status? | Current evidence | Assessment |
|---|---|---|---|
| Future `ok cluster status` | No | No implementation found; a bounded query can evaluate current sources | Evaluator sufficient |
| Future `ok cluster wait` | No | No implementation found; bounded polling/watch plus repeated evaluation can terminate on `True`, `False`, or timeout | Evaluator sufficient |
| Contract Executor completion | No | ADR-030 requires condition-based completion, but O10 already defines evaluation from retained evidence independently of Executor lifetime | Evaluator/evidence outcome sufficient |
| Evidence collection and review | No | O10 requires reproducible retained inputs, hashes, and result | Evaluator plus evidence store sufficient |
| Human troubleshooting | No | Source facts and an explainable on-demand aggregate can be queried together | Evaluator sufficient |
| Monitoring and alerting | Maybe | No OpenKubes monitor requiring this API was found | Could evaluate periodically or ingest evaluator output; not a forcing consumer yet |
| Policy engine | Maybe | No policy depending on continuously current aggregate OpenKubes status was found | Policy semantics and freshness contract must be concrete before B |
| Kubernetes-native Watch | Yes, if promised | No consumer or accepted aggregate API was found | Hypothetical forcing consumer only |
| External controller/automation | Yes, if it relies on transitions without initiating evaluation | No such consumer was found | Hypothetical forcing consumer only |
| CAPI availability gate | Yes, because CAPI would consume a Condition written on the Cluster | Capability exists but no writer/profile/governance decision was selected | Must be justified by a real availability-gate requirement; not current evidence |

`Maybe` and `if promised` do not prove a requirement. Before outcome B is selected, a
consumer must define:

- the exact API/object it watches or queries;
- why on-demand evaluation is insufficient;
- maximum tolerated staleness and outage behavior;
- required transition and replay semantics;
- retention and deletion behavior;
- authorization and multi-tenant visibility; and
- the operational owner of the status writer.

## Mechanism comparison

### Model A — bounded read-only evaluator

```text
authoritative source objects/evidence
              |
              v
deterministic correlation + normalization
              |
              v
Ready=True|False|Unknown + evidence outcome
```

Properties:

- no long-running OpenKubes writer;
- no new source of lifecycle truth;
- deterministic recomputation from versioned inputs;
- suitable for CLI status/wait, Executor completion, CI, and evidence review;
- source reconciliation continues if the evaluator is absent; and
- no Kubernetes-native continuously watchable aggregate object.

An optional cache or evidence store does not change this into a reconciler if it does
not promise continuously current status and cannot mutate lifecycle sources.

### Model B — persistent status adapter

```text
authoritative source objects
              |
              v
continuous correlation + normalization
              |
              v
durable OpenKubes Conditions
```

Properties:

- a long-running OpenKubes-owned control loop is required to keep the aggregate
  current;
- one explicit writer owns only the normalized OpenKubes status surface;
- it maintains transition metadata and watch semantics;
- it becomes unavailable or stale/`Unknown` when required observers are unavailable;
  and
- it never repairs source resources.

Model B is justified only by a concrete consumer that cannot use Model A. If selected,
it is a small B-level status/aggregation component, not a Cluster lifecycle owner.

## Reconciler necessity test

1. **OpenKubes-specific desired state:** the required-condition profile and normalized
   names are OpenKubes semantics.
2. **Can it drift:** source facts can change; a persisted aggregate can become stale.
3. **Does drift matter:** yes for consumers relying on a persisted result.
4. **Continuous detection:** not required by any currently observed consumer; bounded
   evaluation is sufficient for the currently identified workflows.
5. **Repeated correction:** source resources are corrected by their existing owners;
   only a hypothetical persisted status would need repeated updates.
6. **Current owner:** each source domain already has an authoritative controller; no
   aggregate OpenKubes writer exists.
7. **Existing mechanism:** source APIs plus a deterministic evaluator and evidence
   store can answer the currently evidenced use cases.
8. **Deterministic mechanism sufficient:** yes for current status, wait, completion,
   and evidence outcomes, provided all required source identities/revisions exist.
9. **Persistence:** retained evidence is sufficient for operation proof; continuously
   current publication has no forcing consumer.
10. **Stop behavior:** if the evaluator stops, source reconciliation continues. A
    future persistent adapter must report stale/`Unknown` after observation loss and
    must not change lifecycle resources.

**RequiresReconciler for Aggregate Conditions:** `No` based on current evidence.

This `No` is scoped and reasoned: a new OpenKubes-owned control loop is not required to
derive the aggregate outcome for any currently identified consumer. It is not a claim
that continuously published status can never become a product requirement.

## A/B/C/D impact

```text
A — supported for the Aggregate Conditions scope
    A bounded evaluator satisfies every currently evidenced consumer.

B — not proven
    No concrete consumer currently forces continuously published status.

C — not supported by aggregate-status evidence
    Aggregation introduces no source-resource correction or Cluster lifecycle
    ownership.

D — applies to any design where the aggregator repairs or rewrites source domains
    already owned by CAPI, Enablement, GitOps, or allocation authorities.
```

This follow-up resolves the Aggregate Conditions mechanism toward **A-compatible** on
current evidence. It does not by itself classify all of OK-141: unresolved or merely
configurable mechanisms in other domains and the mutation-gated execution evidence
remain outside this result.

## Decision checkpoint

```text
Source ownership:                     existing domain controllers
Condition normalization:              deterministic
Aggregate Ready evaluation:           bounded / read-only
Durable operation evidence:           separate persistence concern
Continuously published status:         no forcing consumer
OpenKubes status adapter:              not proven necessary
OpenKubes lifecycle reconciler:        not required

Aggregate Conditions result:           No new reconciler required
Aggregate Conditions A/B position:     A-compatible; B not proven
OK-141 A/B/C/D:                         unclassified
RequiresReconciler overall:            none proven
Infrastructure:                        NO-GO
Failure Injection:                     NO-GO
```

## Re-evaluation triggers

Re-open the A/B boundary only when at least one concrete consumer requires a
continuously current aggregate, for example:

- an accepted Kubernetes API contract promises Watch semantics;
- a policy decision must consume a current aggregate independently of an operation;
- external automation requires transition events and cannot perform bounded
  evaluation;
- product monitoring requires an authoritative retained Condition rather than derived
  metrics/evidence; or
- CAPI availability gates are selected and require an explicit writer for
  OpenKubes-owned gate Conditions.

Even after such a trigger, the smallest acceptable Model B adapter remains
observe/correlate/aggregate/publish only. Any proposal to repair source resources must
return to the ownership analysis and is presumptively outcome D.
