# OK-141 Overall Evidence Evaluation

Status: **Read-only synthesis; overall A/B/C/D remains unclassified**

Recorded: 2026-08-09

Branch: `spike/OK-141-overall-evidence-evaluation`

Baseline: `main` at `ce064c3`

## Question

What does the complete merged OK-141 evidence establish about the need for
OpenKubes-owned control loops, and is outcome A, B, C, or D proven for the spike as a
whole?

This document consolidates existing evidence. It does not:

- add a new mechanism evaluation;
- select an OpenKubes Operator, public API, CRD, allocator, Enablement provider, or
  GitOps implementation;
- change ADR-030 or ADR-031;
- authorize infrastructure mutation or failure injection; or
- treat a documented capability as execution proof.

Infrastructure mutation and failure injection remain **NO-GO**.

## Evidence checkpoints

The synthesis is based on the following merged checkpoints:

| Checkpoint | Main commit | Evidence boundary |
|---|---|---|
| Pre-mechanism evaluation | `0ef9995` | Existing contracts, responsibility, source Conditions, revision/authority evidence, carrier feasibility, and reconciler-necessity method |
| Allocation Authority | `bf576c8` | Endpoint allocation, fixed endpoint provenance, and Pod/Service CIDR authority |
| Enablement E / `NetworkReady` | `bc34e65` | Deterministic E, existing add-on convergence candidates, runtime sources, and readiness-proof gap |
| Platform P / `PlatformReady` | `117bfb4` | Deterministic P, existing GitOps convergence, applied revision/health evidence, and placement feasibility |
| Aggregate Conditions | `ce064c3` | Source normalization, bounded evaluation, consumer inventory, and A/B publication boundary |

The checkpoints deliberately preserve the distinction between:

```text
capability documented
    != mechanism configured for OpenKubes
    != mechanism proven by execution
    != architecture accepted
```

## Evaluation vocabulary

The reconciler-necessity result is about whether a **new OpenKubes-owned control loop**
is required. It is not an implementation-completeness score.

| Result | Meaning |
|---|---|
| `No` | Evidence shows the gap can be owned by an existing controller, deterministic function/evaluator, authority, or persistence mechanism without a new OpenKubes loop |
| `Unresolved` | Required invariant, forcing consumer, selected mechanism, or execution evidence is still insufficient |
| `Proven` | The complete necessity threshold for a new OpenKubes-owned control loop is satisfied |

A mechanism may be missing, persistent, or operationally critical while still having
`RequiresReconciler=No`. Persistence alone is not Cluster lifecycle reconciliation.

## Consolidated mechanism results

| Domain / gap | Current evidence | Reconciler-necessity result | Overall significance |
|---|---|---|---|
| Contract canonicalization | Versioned deterministic normalization pipeline defined; implementation/fixtures still pending | `No` | A-compatible function, not a controller |
| Intent revision `R` transport and projection | Deterministic projection plus retained identities/digests can carry proof; complete disposable chain unexecuted | `No` | A-compatible operation/evidence concern |
| Durable evidence | Independent persistence and deterministic verification suffice; product store not selected | `No` | A-compatible persistence/audit capability |
| Global lifecycle-writer evidence for ADR-030 | Authority/fencing belongs to ADR-031; zero writers is safe during transitions | `No for ADR-030` | Does not justify an ADR-030 lifecycle loop |
| Endpoint / LoadBalancer address | CAPK plus MetalLB already own allocation and correction | `No` | Existing mechanism sufficient for provider-assigned endpoints |
| Fixed endpoint provenance | Existing provider/Service identities can be correlated when configured and retained | `No` | Configurable evidence, not new ownership |
| Pod/Service CIDR authority | Required uniqueness domain is undefined; no multi-cluster IPv4 authority observed | `Unresolved` | Could be policy/static inventory/external IPAM/authority; no OpenKubes loop proven |
| Enablement revision `E` construction | Immutable chart, values, image, and profile inputs can construct E deterministically | `No` | A-compatible function |
| Enablement package convergence | Existing add-on mechanisms can own drift/retry; CAAPH is configurable but not proven in OpenKubes | `No` for a new OpenKubes package loop | Existing-controller path favored; execution proof pending |
| `NetworkReady` proof | Runtime sources exist; exact E correlation, profile probes, observer-loss behavior, and durable owner are unproven | `Unresolved`, not `Proven` | A evaluator or B publication remains possible; not C evidence |
| Platform revision `P` construction | Profile membership and immutable capability-leaf identities can construct P deterministically | `No` | A-compatible function |
| Platform convergence | Argo CD can own compare/apply/retry/prune/self-heal; no OpenKubes GitOps root is configured | `No` for a new OpenKubes platform loop | Existing GitOps ownership; execution and placement proof pending |
| `PlatformReady` evaluation | Desired/applied P, sync, health, current errors, target identity, and capability checks can be evaluated read-only | `No` for lifecycle correction | A-compatible evaluation; forcing profile unproven |
| Aggregate Conditions | Current consumers can use a fail-closed bounded evaluator | `No` | A-compatible; no persistent status writer required by current evidence |
| Persistent aggregate status | No real Watch/policy/automation consumer with a continuous freshness contract was found | Not proven necessary | B remains a re-evaluation path, not a current result |

Summary:

```text
New OpenKubes lifecycle reconciler required:  none proven
Existing controller ownership:                strongly supported
Deterministic functions/evaluators:            strongly supported
Persistent OpenKubes status adapter:           not proven necessary
Broad OpenKubes Operator:                      not justified
Complete implementation/execution proof:       not yet available
```

## Evidence-supported ownership model

The merged evidence supports the following division as the smallest current
hypothesis:

```text
Contracts / profiles
  -> describe R, E, P, required capabilities, and evaluation policy

Policy / authorization
  -> authorize typed lifecycle transitions

Bounded Contract Executor
  -> validate and submit desired state
  -> collect evidence
  -> remain non-authoritative

CAPI / infrastructure controllers
  -> reconcile Cluster, Machine, and provider lifecycle

Existing Enablement/add-on mechanism
  -> converge declared E and package state

Cilium / Kubernetes workload controllers
  -> reconcile network runtime and publish source facts

Existing GitOps controller
  -> converge P and platform resources

Bounded evaluator
  -> correlate R/E/P and authoritative source observations
  -> derive True/False/Unknown and Ready

Evidence persistence
  -> retain authorization, identities, source artifacts, hashes, and outcome
```

Allocation authority is inserted only when the selected connectivity profile requires
exclusive allocation. Its persistence or transactional behavior would not by itself
make it the OpenKubes Cluster lifecycle owner.

No current evidence adds this box:

```text
OpenKubes lifecycle Operator
  -> re-apply CAPI
  -> repair CNI
  -> repair GitOps resources
```

That design would duplicate existing ownership and would be evaluated as D.

## Overall A/B/C/D evaluation

### A — no new OpenKubes-owned control loop

**Evidence in favor:**

- CAPI/CAPK already own infrastructure and Cluster lifecycle reconciliation.
- CAPK/MetalLB already own endpoint allocation and correction.
- Existing add-on mechanisms can own Enablement package convergence.
- Cilium and Kubernetes already own network runtime convergence.
- GitOps already supplies the required platform drift/retry model.
- R, E, P, canonicalization, evidence, and aggregate readiness can be deterministic
  functions, bounded operations, or persistence concerns.
- No current consumer forces a continuously published OpenKubes status surface.

**Why A is not yet proven overall:**

The existing decision gate allows A only after every unresolved gap is closed by an
existing authority/controller or a sufficient bounded mechanism. The following remain
open:

1. the first connectivity profile has not defined the uniqueness domain for
   Pod/Service CIDRs;
2. the selected Enablement mechanism has not proven bootstrap ordering, immutable E,
   retry/restart, drift correction, and `NetworkReady` negative controls;
3. no authoritative OpenKubes GitOps root has proven exact R-to-P-to-applied-revision
   correlation and platform capability checks;
4. the canonicalization/evaluator/evidence mechanisms are specified but not yet
   implemented and exercised together; and
5. the controlled ADR-030 end-to-end and failure-path spike has not run.

**Assessment:** A is the leading and best-supported hypothesis, but selecting A as the
final OK-141 outcome would currently confuse architecture direction with execution
proof.

### B — bounded OpenKubes adapter, aggregation, or authority loop

Potential B-shaped concerns were tested:

- a persistent aggregate status adapter;
- allocation/reservation authority;
- condition/probe aggregation; and
- evidence persistence.

No forcing consumer currently requires persistent aggregate status. CIDR allocation
may require a durable authority for connected profiles, but the invariant and owner
are unresolved, and an external IPAM or admission-time reservation may suffice.
Evidence persistence is not a corrective control loop.

**Assessment:** B is possible only after new evidence, but it is not proven by any
current gap.

### C — OpenKubes-specific lifecycle reconciliation

No gap satisfies the complete C threshold:

```text
OpenKubes-specific desired state
AND meaningful post-submission drift
AND continuous detection required
AND repeated correction required
AND no existing authoritative owner
AND bounded mechanism insufficient
AND no duplicated ownership
```

The demonstrated corrective loops already belong to CAPI, providers, add-on/CNI
controllers, GitOps, or a future declared IPAM authority.

**Assessment:** C is not supported by current evidence. A broad OpenKubes lifecycle
Operator must not be implemented on the basis of OK-141 as it stands.

### D — duplicated ownership

D is a rejection result for a proposed implementation, not evidence that a required
capability should remain missing. The current evidence identifies the following as D:

- OpenKubes re-applying or repairing CAPI-owned resources;
- OpenKubes managing Helm/Cilium resources in parallel with the selected Enablement
  owner;
- OpenKubes applying/pruning/self-healing platform resources in parallel with GitOps;
- an aggregate-status component mutating source resources; or
- an allocator competing with provider/IPAM ownership.

**Assessment:** the evidence-supported hypothesis avoids D. Any later implementation
introducing these overlaps must be rejected or have its ownership boundaries cut
again.

## Overall verdict

```text
A:  leading hypothesis; not yet proven overall
B:  not proven
C:  not supported by current evidence
D:  rejection criterion; current hypothesis avoids it

Overall OK-141 A/B/C/D:            unclassified
RequiresReconciler:                none proven
Broad OpenKubes Operator:          not justified
Public OpenKubes API:              not justified by this evidence
Persistent Status Adapter:         not proven necessary
Infrastructure:                    NO-GO
Failure Injection:                 NO-GO
```

This is a classification result, not indecision: the spike has excluded broad C and
identified ownership-duplicating D designs while leaving A versus a narrowly forced B
to execution and the remaining authority/profile evidence.

## Remaining closure work

### Read-only/product-contract closure

Before a mutation GO is considered, the forcing disposable profile must declare:

1. whether the Cluster is isolated, routed, or mesh-connected and the resulting CIDR
   uniqueness domain;
2. the candidate allocation authority or reviewed bounded/static policy;
3. exact immutable Enablement profile membership and semantic E construction;
4. the candidate existing Enablement mechanism to compare in the spike;
5. exact platform profile membership and semantic P construction;
6. one candidate GitOps root and target identity model for the disposable test;
7. the required-condition profile and source/freshness contracts; and
8. exact canonicalization, evaluator, and evidence artifact versions.

These are test-contract decisions, not acceptance of a public product API or permanent
component.

### Non-invasive implementation/evaluation

The next implementation work can remain free of infrastructure mutation:

- implement the versioned canonicalization fixtures/harness;
- implement or script the bounded fail-closed evaluator over retained fixtures;
- build positive and negative fixtures for stale generation, wrong R/E/P, missing
  source, conflicting authority, and historical success;
- define the evidence manifest and independent verification path; and
- render/diff the candidate existing controller resources without applying them.

This work should reuse one authoritative library/function for interpretation; CLI and
any later server-side consumer must not become independent Contract-to-CAPI compilers.

### Mutation-gated execution proof

Only a new checksum-bound GO may authorize the disposable test. The test must then
prove at minimum:

- accepted R survives Executor termination/restart;
- CAPI/CAPK reconcile the intended object and provider identity chain;
- the selected existing Enablement mechanism converges exact E and restores drift;
- `NetworkReady` fails closed for stale/missing/failed runtime evidence;
- the selected GitOps mechanism converges exact P and exposes current applied
  revision/health;
- aggregate evaluation rejects stale or mismatched R/E/P and successful process exit;
- deletion performs controlled cleanup and preserves terminal evidence; and
- the management-plane outage scenario resumes with exactly one replacement, while
  ADR-031 authority/fencing proof remains a separate DR concern.

Happy-path success alone cannot classify or accept ADR-030.

## ADR impact after execution evidence

ADR-030 remains `Proposed` and unchanged by this synthesis. If the A-compatible
hypothesis survives the controlled spike, review before `Accepted` must at least:

- replace the mandatory continuously running OpenKubes Status Aggregator with a
  deterministic aggregate-result invariant, allowing a bounded evaluator unless a
  forcing consumer proves B;
- describe Enablement ownership as an existing selected controller mechanism rather
  than presupposing a new OpenKubes controller;
- align historical `ControlPlaneReady` naming with current CAPI
  `ControlPlaneAvailable` semantics;
- preserve single-writer ownership for every actual persisted status surface; and
- keep ADR-031 authority/fencing and disaster recovery separate from ADR-030
  execution ownership.

No ADR text should be changed merely to match the leading hypothesis before the
required execution evidence is reviewed.

## Re-evaluation triggers

Re-evaluate the overall classification when:

- the connectivity profile proves that an OpenKubes-owned transactional allocation
  authority is unavoidable;
- a real product consumer proves continuous aggregate Watch/freshness semantics;
- no existing Enablement mechanism can own required E convergence without ownership
  duplication;
- no existing GitOps mechanism can own required P convergence;
- the disposable test reveals OpenKubes-specific drift that no existing authority can
  detect and correct; or
- a proposed implementation begins writing state already owned by another domain.

The threshold remains evidence, not component preference.
