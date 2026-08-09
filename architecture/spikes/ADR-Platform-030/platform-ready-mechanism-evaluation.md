# Platform P and PlatformReady Mechanism Evaluation

**Ticket:** OK-141

**Baseline:** `main` at `bc34e65`

**Input:** [platform-ready-observation.md](platform-ready-observation.md)

**Placement input:**
[ok-shared-gitops-placement-feasibility.md](ok-shared-gitops-placement-feasibility.md)

**Evaluation date:** 2026-08-09

**Infrastructure mutation:** `NO-GO`

## Question

Can an existing GitOps mechanism own desired platform revision `P`, continuously
converge it, and supply enough authoritative evidence to derive `PlatformReady`, or is
new OpenKubes-owned reconciliation necessary?

## Result

```text
Semantic P construction                   Deterministic mechanism sufficient
Desired P ownership and convergence        Existing mechanism configurable
Per-Application revision/sync/health        Native capability sufficient in principle
Current OpenKubes profile root              Missing
Datacenter GitOps placement                 ok-shared recommended; current NO-GO
PlatformReady evaluation                    Deterministic mechanism configurable
Durable PlatformReady publication           Still unresolved

Overall Platform P / PlatformReady          Still unresolved
RequiresReconciler                          none proven
A/B/C/D                                     unclassified
```

Argo CD is an existing controller implementation capable of supplying the corrective
platform loop, but no OpenKubes Argo instance or platform root is currently observed.
The remaining OpenKubes work is to select/configure a reviewed GitOps profile, correlate
its exact revision and required Applications, and evaluate native status fail-closed.
None of that currently requires OpenKubes to implement GitOps reconciliation itself.

## Candidate semantic revision P

`P` should describe one semantic platform profile, not one arbitrary Argo field:

```text
canonicalization profile
+ platform profile identity/version
+ target Cluster immutable identity
+ ordered required-Application identities
+ immutable source revision vector per Application
+ normalized source parameters/values identity
+ required health and capability-check contract
-> SHA-256 P
```

This construction is deterministic and versioned. It is not a control loop.

For Git sources, the applied carrier should resolve to an immutable commit. For Helm or
OCI sources, it should use an immutable artifact identity where the implementation can
expose one; a mutable tag or chart repository entry alone is weaker evidence. A
multi-source Application contributes a revision vector to `P`.

The following are explicitly not `P`:

- `targetRevision: main` by itself;
- Application `metadata.generation`;
- the time of the last successful operation;
- one child Application's revision; or
- the digest of unnormalized YAML text.

`P` should be a composition of capability-owned leaf identities, not a replacement for
them. For example, an observability leaf can retain the immutable
`ok-observability` commit plus its profile/config identity and Contract-Test contract.
Ingress, secrets, storage, and diagnostics require equivalent declared leaf identities
only when the selected profile includes them.

Application workloads such as Open WebUI or OpenClaw do not automatically belong to
Platform `P`. They remain `ok-apps`/workload concerns unless a reviewed platform profile
explicitly makes one a required platform capability. This prevents `PlatformReady` from
silently becoming "every workload is healthy."

## Revision carrier feasibility

| Source form | Desired carrier | Observed/applied carrier | Acceptance for `P` | Current assessment |
|---|---|---|---|---|
| Git pinned commit | repository, path, exact commit, normalized parameters | current Argo sync revision plus matching `comparedTo` | exact commit equality | Configurable; strongest Git profile |
| Git branch or symbolic ref | repository, path, qualified ref, normalized parameters | currently resolved commit | ref alone never passes; resolved commit must be current and becomes the leaf identity | Configurable with fail-closed resolution |
| Git tag | repository, path, tag, normalized parameters | resolved commit | tag plus exact resolved commit; retagging creates a new leaf identity | Configurable, weaker than direct commit pin |
| Helm repository | repository, chart, exact version, normalized values | current applied chart revision/version | exact version plus immutable artifact evidence where available | Configurable; artifact mutability remains to prove |
| Multi-source Application | ordered normalized source list including `ref` aliases | ordered applied revision vector | every desired source maps one-to-one to the current vector | Configurable; scalar revision is insufficient |
| Raw remote manifest URL | URL embedded in procedural command | no common applied source identity | must be replaced by a content digest or vendored immutable capability revision | Insufficient as-is |

Argo documents that branch and symbolic references move, tags may be moved, and commit
SHAs are the stable pinning form. Helm version ranges are also moving selectors. A
production forcing profile should therefore prefer exact immutable inputs and must
retain the actual resolved identity used for reconciliation.

References:

- [Argo CD tracking and deployment strategies](https://argo-cd.readthedocs.io/en/stable/user-guide/tracking_strategies/)
- [Argo CD declarative Application and cluster model](https://argo-cd.readthedocs.io/en/latest/operator-manual/declarative-setup/)

## Current-spec correlation without observedGeneration

The observed Argo Application status did not expose a
`status.observedGeneration` equivalent. A generation number must therefore not be
invented or inferred from timestamps. The candidate fail-closed rule is semantic
correlation:

```text
normalize(current spec source(s), destination, project, relevant sync inputs)
==
normalize(status.sync.comparedTo source(s), destination, project-relevant inputs)

AND current applied revision vector == P leaf revision vector
AND Sync == Synced
AND Health == Healthy
AND no current error Condition or invalid operation exists
```

This rule is configurable but still requires a disposable OpenKubes profile test. If
Argo omits a semantic spec field from `comparedTo`, the forcing profile must find another
native correlation carrier or mark the result `Unknown`; a timestamp or old successful
operation may not fill the gap.

## Mechanism assessment

### Argo CD Application controller

**Assessment:** existing mechanism configurable for desired platform ownership and
continuous convergence.

Once selected and configured as the authoritative GitOps implementation, Argo CD owns:

- target-state comparison;
- automated sync;
- drift detection and self-heal;
- prune behavior;
- retry/operation state;
- requested and applied source revisions; and
- per-Application resource health.

Those are the exact corrective responsibilities a separate OpenKubes platform
reconciler would otherwise duplicate. OpenKubes may deterministically project a reviewed
profile into Argo Application resources, but Argo must remain their sole GitOps owner.

The observed installation on `ok-infra` belongs to an unrelated test project. It is not
an OpenKubes candidate, authority, or placement decision. It supplies only external
behavior examples; upstream documentation establishes the mechanism capability. No
OpenKubes deployment, `ok-ai` registration, or platform root has been proven. The result
therefore remains `configurable`, not `sufficient`.

References:

- [Argo CD core concepts](https://argo-cd.readthedocs.io/en/stable/core_concepts/)
- [Automated sync and self-heal](https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/)

### App-of-Apps root

**Assessment:** configurable composition root, insufficient as an implicit transitive
`PlatformReady` aggregate.

Argo's own bootstrapping guidance shows that a parent can be in sync while child
Applications remain out of sync. Health assessment for the `Application` CRD is not an
automatic transitive child-health contract. The unrelated test project's `app-sync`
parent supplies an external negative example: it remained `Healthy` while source
comparison failed and its child resource sync states were unknown.

A profile may still use App-of-Apps, but readiness must evaluate the deterministic child
set and not trust the parent Health field alone.

References:

- [Argo CD cluster bootstrapping / App-of-Apps](https://argo-cd.readthedocs.io/en/stable/operator-manual/cluster-bootstrapping/)
- [Argo CD resource health](https://argo-cd.readthedocs.io/en/release-3.5/operator-manual/health/)

### ApplicationSet

**Assessment:** configurable membership/generation mechanism, not required by current
evidence and not itself the platform outcome.

ApplicationSet can deterministically generate Applications and expose generator
conditions. It could be useful when a forcing profile needs multi-cluster or parameterized
membership. No ApplicationSet object is present today, and OpenKubes does not need to
introduce one merely to create a component box. Generated child Applications remain the
authoritative convergence/status units.

### Read-only PlatformReady evaluator

**Assessment:** deterministic mechanism configurable for operation completion and
evidence; durable publication remains unresolved.

An evaluator can consume the declared profile and current Application objects without
writing their desired state. It should fail closed and produce an outcome linked to the
exact input object hashes and `P`.

That evaluator is sufficient for `submit -> observe -> collect evidence -> outcome` if
the forcing consumer only needs bounded operation completion. It does not correct
platform resources; Argo continues to do that.

If a product consumer requires a continuously queryable, persisted Kubernetes
`PlatformReady` condition, a small status adapter may be justified later. That is an
A/B question, not evidence for an OpenKubes Cluster lifecycle owner.

### Existing imperative capability paths

**Assessment:** useful leaf provenance and contract probes exist, but the current paths
are insufficient as a durable platform owner.

The current Make/Helm/kubectl workflows install independent capabilities. In particular,
the observability path already resolves a pinned capability-repository commit and runs a
capability-owned functional gate. This demonstrates that OpenKubes can compose existing
capability contracts rather than invent generic health checks.

The process exits after install, however. Its printed commit identities and gate result
are not a continuously refreshed platform status, and no common profile declares which
capabilities are required. Re-running these scripts from an OpenKubes Operator would
merely turn procedural submission into a custom package reconciler and duplicate the
selected GitOps owner.

The safer projection is:

```text
OpenKubes platform profile
    -> selects versioned capability leaves
GitOps Application(s)
    -> continuously converge each leaf
capability-owned status/contract probes
    -> prove functional readiness
read-only evaluator
    -> correlate all required leaves with P
```

## GitOps placement profile

The agreed working hypothesis for a later implementation test is:

> Use a central GitOps controller on `ok-shared` as the datacenter default. Use an
> in-workload GitOps controller only where a constrained-edge, offline, or autonomy
> envelope requires it.

This is a spike recommendation, not an installed component, accepted public API, or
authorization to mutate `ok-shared`. Controller semantics and `P` remain
placement-independent.

The evaluated profiles are:

| Placement profile | Bootstrap boundary | Outage behavior | Unresolved proof |
|---|---|---|---|
| central on `ok-shared` | bootstrap `ok-shared` and GitOps independently before registering workload targets | continues during a pure `ok-mgmt` outage; all central platform convergence pauses during `ok-shared` outage | recovery/HA, scoped credentials, target reachability, shared-services blast radius |
| central on `ok-mgmt` | available after management bootstrap; workload registration required | platform convergence pauses with Tier-0 management outage | not preferred because it couples lifecycle and platform convergence failure domains |
| dedicated OpenKubes GitOps plane | separately bootstrapped authority | independent of one workload and potentially of `ok-mgmt` | extra Tier-0/DR boundary and operating cost; no forcing consumer today |
| in each workload Cluster | installed only after Enablement/`NetworkReady` | local convergence can continue independently of management/shared services | datacenter overhead; useful when edge/offline autonomy forces it |

The unrelated Argo CD installation on `ok-infra` is not a fourth option.

Whichever profile is selected later must satisfy the same invariants:

- at most one GitOps writer owns a given platform resource set;
- the target is linked to immutable OpenKubes Cluster identity, not merely a reusable
  name or API URL;
- credentials are scoped, rotated, and recoverable without a permanently privileged
  Executor kubeconfig;
- GitOps outage pauses convergence but does not transfer resource ownership to the
  Executor;
- controller restart resumes reconciliation of the already accepted desired state;
- `P` construction and `PlatformReady` evaluation remain placement-independent; and
- no placement is adopted from an unrelated installation by convenience.

### Preconditions for the ok-shared datacenter profile

Before installation or acceptance, a separate mutation-gated test must prove:

1. `ok-shared` recovery and availability objectives, including whether its current
   single control-plane replica is acceptable or must become highly available;
2. network and TLS reachability from `ok-shared` to every selected workload API;
3. least-privilege, rotatable, recoverable per-Cluster credentials and AppProject
   boundaries rather than shared cluster-admin access;
4. Git/OCI/artifact access for every selected constraint envelope;
5. backup/restore or deterministic reconstruction of Applications, projects,
   repositories, registration metadata, and required credentials;
6. exactly one GitOps writer for each managed platform resource set;
7. continued workload operation plus explicitly paused platform convergence during an
   `ok-shared` outage, followed by deterministic resume;
8. bootstrap and recovery for Argo CD itself that does not depend on the unavailable
   Argo CD instance;
9. no ownership of CAPI lifecycle or pre-network CNI Enablement; and
10. exact `R -> P -> Application revision -> capability check` evidence.

Argo may later self-manage reviewed configuration after bootstrap, but the initial
install and disaster-recovery path must remain independently executable.

> **The GitOps control plane must be recoverable without depending on its own successful
> reconciliation.**

## PlatformReady acceptance model

For current `P`, `PlatformReady=True` should require:

```text
authoritative profile root exists and targets the expected Cluster identity
AND profile root is linked to current OpenKubes revision R
AND deterministic required-Application membership equals the profile definition
AND every required Application still exists with the expected UID/identity
AND current Application spec/destination equals the normalized input represented by P
AND status.sync.comparedTo corresponds to that current spec/destination
AND requested mutable references resolve to the immutable revision vector in P
AND status.sync.status == Synced
AND status.health.status == Healthy
AND no ComparisonError, SyncError, or failed/running operation invalidates the result
AND every required capability-owned contract check passes
AND observation and evidence freshness satisfy the declared contract
```

`Application.status.operationState.phase=Succeeded` is historical operation evidence,
not current readiness. `Health=Healthy` and `Sync=Synced` are both necessary but are not
alone sufficient for the full profile.

## Negative controls

Each of these must make `PlatformReady` false or unknown:

| Negative control | Required outcome |
|---|---|
| `Healthy` with `Sync=Unknown` | Not Ready |
| `Healthy` with `Sync=OutOfSync` | Not Ready |
| Current comparison/authentication error after an old successful operation | Not Ready |
| Requested symbolic branch with no current immutable resolved commit | Blocked/Unknown |
| Correct revision on only one source of a multi-source Application | Not Ready |
| Parent root synced while a required child is not | Not Ready |
| Extra/missing required Application versus current profile membership | Not Ready |
| Correct Argo status for the wrong target Cluster identity | Not Ready |
| Application healthy but a declared platform capability check fails | Not Ready |

The unrelated test-project snapshot already demonstrates the first three status
combinations without failure injection. They are behavior examples, not OpenKubes
acceptance evidence.

## Fail-closed outcome semantics

The evaluator can define deterministic outcome semantics without defining a new CRD:

| Outcome | Meaning | Example reason |
|---|---|---|
| `True` | every required leaf is current, synced, healthy, identity-correct, and contract-verified for exact `P` | `PlatformProfileConverged` |
| `False` | an authoritative current source proves non-convergence or failed capability | `ApplicationOutOfSync`, `ApplicationDegraded`, `CapabilityCheckFailed` |
| `Unknown` | current truth cannot be established safely | `ComparisonError`, `RevisionUnresolved`, `EvidenceStale`, `TargetIdentityUnproven` |
| blocked test outcome | the requested profile root or required observer does not yet exist | `MissingPlatformRoot`, `MissingObserver` |

An implementation may later map a blocked test outcome to a Kubernetes Condition, CLI
result, or evidence status. This spike does not select that publication API. It only
requires that missing or stale proof never becomes `True` and that an old successful
operation never overrides a current `False` or `Unknown` source.

## Reconciler necessity test

1. **OpenKubes-specific desired state:** the selected profile and its membership are
   OpenKubes semantics; the rendered Application desired state is standard Argo
   semantics.
2. **Can it drift:** yes; Git revisions, rendered resources, and runtime health can
   diverge.
3. **Does drift matter:** yes; platform capability may cease to satisfy its profile.
4. **Continuous detection:** yes.
5. **Repeated correction:** yes for platform resources.
6. **Existing controller implementation:** yes; Argo CD can own comparison, apply,
   retry, prune, self-heal, and Application health. No authoritative OpenKubes instance
   is currently configured.
7. **Deterministic operation/evaluator sufficient:** sufficient for constructing `P`
   and evaluating an operation outcome, not for correcting platform drift.
8. **Duplicate ownership risk:** high if OpenKubes also applies or repairs the same
   resources.
9. **Persistence:** Git plus Argo Application status persists desired and observed
   platform state; independent evidence persists the evaluated outcome.
10. **Stop behavior:** if Argo stops, platform correction pauses but CAPI lifecycle and
    already-running platform workloads do not become owned by the Executor.

**RequiresReconciler:** `No` for a new OpenKubes-owned platform lifecycle loop.

**Durable aggregate publication:** `Unresolved`. A bounded read-only evaluator is
plausible; a continuously current status surface requires a forcing consumer before a
small B-level adapter can be justified.

## Why this does not prove an OpenKubes operator

```text
OpenKubes profile function -> construct P and required membership
Argo CD                   -> reconcile platform Applications/resources
Application/source owners -> publish revision, sync, health, and resource facts
evaluator                 -> correlate those facts with R and P
OpenKubes status adapter  -> only if a forcing consumer requires durable publication
```

No current evidence requires OpenKubes to apply, prune, retry, self-heal, or otherwise
repair platform resources. Implementing those actions in an OpenKubes Operator would be
outcome `D`: duplicated ownership.

## Next evidence

A later mutation-gated disposable profile should prove, without preselecting a new
component:

1. one explicit root or deterministic required-Application set for the disposable
   Cluster;
2. immutable capability-leaf source and artifact revisions that construct `P`;
3. target Cluster identity and `R -> P` correlation;
4. current `Synced` plus `Healthy` for every required Application;
5. restart/retry and self-heal through the selected OpenKubes GitOps controller;
6. negative controls for wrong revision, missing child, comparison error, out-of-sync,
   degraded health, and failed profile check; and
7. bounded evidence evaluation independently of Executor lifetime.

Until a separate GO authorizes that test:

```text
P construction:                 deterministic
P convergence:                  configurable
Per-Application source fields:  sufficient in principle; OpenKubes profile unproven
Datacenter placement:            ok-shared recommended; feasibility NO-GO
PlatformReady evaluation:       configurable / unproven for an OpenKubes profile
PlatformReady publication:      unresolved
OpenKubes platform loop:        not proven necessary

RequiresReconciler:             none proven
A/B/C/D:                        unclassified
Infrastructure:                 NO-GO
Failure Injection:              NO-GO
```
