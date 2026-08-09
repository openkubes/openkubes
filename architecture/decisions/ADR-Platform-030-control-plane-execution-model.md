# ADR-Platform-030: Cluster Lifecycle Control-Plane Execution Model

**Date:** 2026-08-09
**Status:** Proposed

**Clarifies:** ADR-Platform-004
**Extends:** ADR-Platform-007, ADR-Platform-011
**Related:** ADR-Platform-001, ADR-Platform-003, ADR-Platform-013, ADR-Platform-015, ADR-Platform-017, ADR-Platform-021, ADR-Platform-023

---

## Context

The historical `capi-platform-v4.2` implementation combined two sound ideas with a
procedural execution path:

1. a declarative CAPI/CAPK desired state persisted in the management cluster; and
2. a versioned Docker runner that rendered and applied that state.

The runner was useful, but it also performed operational steps after submission:
creating namespaces and infrastructure secrets, fetching the workload kubeconfig,
installing CNI and Multus, waiting for the API and Nodes, and cleaning up. The runner
therefore held temporary execution state and generated artifacts even though it was
not authoritative for the long-lived Machine lifecycle.

ADR-Platform-004 correctly records the runner as an implementation detail. It does
not, however, define the architectural role behind that implementation detail, how
cluster operations change desired state, where minimum cluster viability ends and
normal GitOps begins, or how completion is observed without relying on a successful
shell process.

GitOps alone does not reliably solve initial cluster networking. A GitOps controller
running in the new workload cluster may not become schedulable or operational before
the CNI exists. Calling this phase "bootstrap" would be ambiguous because Cluster API
already uses `BootstrapConfig` for node initialization mechanisms such as kubeadm and
Talos bootstrap providers.

OpenKubes therefore needs an explicit control-plane execution model that separates:

- description of intent;
- authorization of a transition;
- submission of the authorized desired state;
- infrastructure and Cluster lifecycle reconciliation;
- establishment of minimum cluster viability; and
- convergence of the durable platform configuration.

## Decision

OpenKubes adopts a six-layer Cluster Lifecycle Control-Plane Execution Model:

```text
1. Intent / Contract
   -> describes the desired state

2. Policy / Authorization
   -> decides whether the requested transition is allowed

3. Contract Execution
   -> validates, submits, observes, and records the authorized transition

4. Infrastructure / Cluster Lifecycle
   -> CAPI and its infrastructure, control-plane, and bootstrap providers
      reconcile infrastructure, Machines, and the Kubernetes control plane

5. Cluster Enablement
   -> establishes minimum cluster viability: networking and any other
      declared prerequisites required before normal platform reconciliation

6. Platform Reconciliation
   -> GitOps converges the durable platform configuration
```

The normative summary is:

> **Contracts describe. Policies authorize. Executors submit. Controllers reconcile.
> Enablement activates. GitOps converges.**

Two additional invariants govern all interfaces:

> **OpenKubes exposes operations, not shells.**

> **Operations mutate contracts; they do not bypass them.**

Two hard lifecycle invariants follow:

> **A cluster lifecycle operation is successful only when the requested contract
> generation has been reconciled to all profile-required Conditions for that
> generation. Successful termination of an Executor process is not evidence of
> lifecycle success.**

> **Executor failure must not invalidate, roll back, or orphan an already accepted
> desired-state transition.**

### 1. Intent and authoritative desired state

The Cluster Lifecycle Contract is the sole authoritative description of an OpenKubes
cluster's desired state. A concrete API such as `OpenKubesCluster` may expose that
contract. Git may be the authoritative persistence and review path for instances of
the contract, with GitOps materializing them into the Kubernetes API. Alternatively,
an authorized API path may persist the contract directly.

This ADR does not select between those persistence profiles. It requires each profile
to declare exactly one authoritative desired-state path. Git, a platform CR, rendered
manifests, runner-local files, and workflow records MUST NOT become competing sources
of truth.

An illustrative contract shape is:

```yaml
apiVersion: platform.openkubes.io/v1alpha1
kind: OpenKubesCluster
metadata:
  name: ok1
spec:
  kubernetes:
    version: v1.x

  infrastructure:
    provider: kubevirt
    profile: standard

  enablement:
    network:
      provider: cilium
      version: "..."
    storage:
      profile: standard

  platform:
    profile: standard
```

This schema is illustrative, not a v1alpha1 API acceptance act. Provider values,
profile schemas, defaulting, upgrade compatibility, and deletion policy require API
design and contract tests before the CRD is accepted.

### 2. Operations are authorized contract transitions

`CreateCluster`, `ScaleCluster`, `UpgradeCluster`, `DeleteCluster`,
`ChangeNetworkProfile`, and `ApplyPlatformProfile` are semantic operations. An
operation MUST:

1. read or construct the current contract;
2. validate the requested transition against its schema and transition rules;
3. obtain an authorization or policy decision;
4. mutate the authoritative contract through its declared persistence path;
5. observe the resulting generation and Conditions; and
6. record durable evidence of the decision and outcome.

An operation MUST NOT create a second imperative workflow truth. For example:

```text
ok cluster upgrade ok1 --kubernetes-version v1.36.x
  -> authorize spec.kubernetes.version v1.35.x -> v1.36.x
  -> persist the new desired state
  -> observe reconciliation of the new generation
```

It MUST NOT mean "run an independent `upgrade-cluster.sh` whose state is authoritative
outside the contract." Implementations may use Jobs, scripts, or workflows internally,
but those mechanisms remain replaceable and non-authoritative.

Deletion follows the same rule. The operation requests deletion through the
authoritative contract and observes controller finalization; it does not silently
delete provider resources behind the contract.

### 3. Contract Executor role

The architectural role is **Contract Executor**. "Runner" names one possible technical
form of that role.

An Executor:

- validates syntax and transition preconditions;
- submits only an already-authorized transition;
- observes deterministic status Conditions for the submitted generation;
- collects and returns evidence; and
- may retry submission and observation idempotently.

An Executor:

- does not own the Cluster or Machine lifecycle;
- does not independently decide policy;
- does not expose unrestricted shell, Helm, or `kubectl` access as the platform API;
- does not keep the only copy of desired state or outcome; and
- does not turn a successful process exit into the definition of Cluster readiness.

The Executor is therefore **non-authoritative**, not necessarily stateless. It may hold
temporary state, correlation IDs, rendered artifacts, or observation checkpoints, but
loss of that state must not change the declared desired state or stop controller
reconciliation. A restarted Executor must be able to resume observation from durable
platform state.

An Executor may be implemented as a CLI, Kubernetes Job, controller, API service, or CI
workflow. Its implementation form does not change the contract.

### 4. Infrastructure and Cluster lifecycle

CAPI and the selected infrastructure, control-plane, and CAPI bootstrap providers own
the long-lived reconciliation of infrastructure, Machines, node initialization, and
the Kubernetes control plane. The responsibility split from ADR-Platform-007 remains:
the appropriate management plane owns the workload Cluster resources, while provider
selection remains an Implementation Profile as described by ADR-Platform-023.

The Executor submits desired state; it does not replace these reconcilers.

### 5. Cluster Enablement

OpenKubes names the post-control-plane, pre-platform phase **Cluster Enablement**. It is
distinct from CAPI `BootstrapConfig`.

Cluster Enablement establishes the minimum viability required by the selected profile.
Its baseline responsibility is a healthy CNI and working Pod networking. A profile may
also require cloud-controller integration, CSI, DNS, certificate prerequisites, or a
remote GitOps registration mechanism when those are necessary before normal platform
reconciliation can proceed.

Requirements are profile-dependent. Storage, for example, MUST NOT be an unconditional
readiness requirement for a profile that declares no storage dependency.

A component belongs to Enablement only when its absence prevents the selected cluster
profile or its declared GitOps reconciler from becoming operational. Components needed
by applications after that point belong to Platform reconciliation. The default
boundary is:

| Component or responsibility | Default owner | Qualification |
|---|---|---|
| CNI and Pod networking | Enablement | Always required |
| Provider cloud-controller integration | Enablement | Only when required for Nodes, addresses, routes, or LoadBalancers needed for minimum viability |
| CSI driver | Enablement or Platform | Enablement only when the declared GitOps/profile control plane requires dynamic persistent storage before it can operate; otherwise Platform |
| GitOps controller activation or remote registration | Enablement | Only the minimum mechanism needed to start normal reconciliation |
| `metrics-server` | Platform | Not a prerequisite for baseline Kubernetes or GitOps operation |
| ingress and `cert-manager` | Platform | Unless a specific profile proves one is a prerequisite for authenticated GitOps activation |
| observability, shared services, and applications | Platform | Durable platform configuration |

Crossing `EnablementReady=True` ends the enablement *phase*, not the Enablement
controller's ownership. Enablement components continue to be health- and
version-reconciled by their declared owner. Platform reconciliation MUST NOT also own
or mutate those same resources. Each profile must publish its exact ownership set and
the Conditions that prove the boundary.

Enablement MUST be reconciled by a declarative, observable mechanism. Eligible
implementations include a dedicated add-on controller, a suitable CAPI add-on provider,
management-cluster-driven remote reconciliation, or another controller-based profile.
`ClusterResourceSet` may be used only where its apply and upgrade semantics satisfy the
declared contract; one-time application alone is not assumed to provide continuous
health or version reconciliation.

The historical runner's direct `kubectl apply` of CNI is a migration source, not the
target responsibility model.

### 6. Platform reconciliation

After Enablement establishes the declared minimum viability, GitOps owns convergence of
the durable platform profile: observability, ingress, storage services when declared,
shared services, applications, and other platform capabilities.

GitOps must not be treated as the initial CNI mechanism when its own reliable operation
depends on that CNI. A management-cluster GitOps profile with proven remote application
semantics may implement parts of Enablement, but it must still report the Enablement
Conditions separately from Platform reconciliation.

### 7. Deletion semantics

`DeleteCluster` is an authorized transition through the authoritative contract path.
For an API-backed profile it results in Kubernetes deletion semantics, including
`deletionTimestamp` and controller-owned finalizers; for a Git-backed profile the
reviewed removal is reconciled into the equivalent API deletion. The Executor only
submits and observes this transition.

Every controller that creates lifecycle resources MUST own a distinct finalizer or an
equivalent controller-visible cleanup obligation. It must expose cleanup progress and
failure through Conditions or the durable operation record. Platform de-registration,
Enablement cleanup, provider resource cleanup, credential revocation, and retention or
orphan policy must be explicit in the selected profile. Finalizers MUST NOT be stripped
automatically merely because an Executor timeout expired; force-finalization is a
separate, authorized break-glass operation with evidence of the residual resources.

Deletion succeeds only when:

1. all declared cleanup obligations are complete, or an explicit retention/orphan
   policy accounts for the remaining resources;
2. lifecycle finalizers have completed and the authoritative cluster object is gone;
3. infrastructure absence has been verified to the level promised by the provider
   profile; and
4. the terminal deletion evidence has been persisted outside the object being deleted
   and remains available according to the retention policy.

Successful submission of a delete request, disappearance of the Executor, or deletion
of only the top-level contract is not evidence of successful lifecycle deletion.

## Lifecycle state machines

The model has three independently observable state machines:

```text
Infrastructure lifecycle
  Pending -> Provisioning -> Ready -> Updating -> Deleting

Enablement lifecycle
  WaitingForAPI -> InstallingNetwork -> NetworkReady -> EnablementReady

Platform lifecycle
  Reconciling -> Ready -> Drifted -> Reconciling
```

These names describe the architectural phases; implementations may expose more detailed
Reasons without introducing a second lifecycle truth.

## Conditions and readiness

OpenKubes lifecycle status MUST use Kubernetes `metav1.Condition` semantics rather than
independent boolean fields. At minimum, the aggregate contract exposes or normalizes:

- `InfrastructureReady`;
- `ControlPlaneReady`;
- `NetworkReady`;
- `EnablementReady`;
- `PlatformReady`; and
- an aggregate `Ready` Condition.

Each Condition MUST include `status`, `reason`, `observedGeneration`, and
`lastTransitionTime`; a useful `message` SHOULD be present when the Condition is not
`True`. Consumers MUST treat a Condition whose `observedGeneration` is older than the
resource's current `metadata.generation` as stale for the current desired state.

`Ready` is derived and MUST NOT be independently asserted. Its required inputs are
defined by the selected profile. Conceptually:

```text
Ready = all profile-required Conditions are True
        for the current observed generation
```

A condition adapter may normalize provider-specific Conditions into the OpenKubes
surface. It must preserve causal detail through `reason` and `message`; normalization
must not hide a provider failure.

Condition ownership is single-writer and explicit:

| Condition | Source of truth | Sole writer on the aggregate OpenKubes status |
|---|---|---|
| `InfrastructureReady` | Infrastructure/CAPI resources | OpenKubes Status Aggregator |
| `ControlPlaneReady` | CAPI control-plane and Cluster resources | OpenKubes Status Aggregator |
| `NetworkReady` | Cluster Enablement reconciler | OpenKubes Status Aggregator |
| `EnablementReady` | Cluster Enablement reconciler | OpenKubes Status Aggregator |
| `PlatformReady` | Selected GitOps/platform reconciler | OpenKubes Status Aggregator |
| `Ready` | Derived from the profile-required normalized Conditions | OpenKubes Status Aggregator |

Source controllers continue to own Conditions on their own resources. Exactly one
OpenKubes Status Aggregator owns the normalized Conditions on the aggregate contract;
Executors, provider controllers, Enablement implementations, and GitOps controllers do
not concurrently write that aggregate Condition set. The Aggregator may report the
current OpenKubes `observedGeneration` only after every required source observation has
been correlated with the desired projection of that generation. Until then the
Condition is `Unknown` or carries an older `observedGeneration`; prior `True` values
must not be copied forward optimistically.

Successful Executor exit, API reachability, or CAPI `ControlPlaneReady` alone does not
mean the OpenKubes cluster is `Ready`.

## Evidence and completion

Submission returns a durable operation/correlation identifier and the accepted desired
generation or Git revision. Completion is evaluated against declared Conditions for
that revision, not against elapsed time or process survival.

Evidence MUST be sufficient to answer:

- who or what requested the transition;
- which prior and requested contract revisions were involved;
- which policy decision authorized or rejected it;
- which generation or Git revision was observed;
- which Conditions and Reasons determined the outcome; and
- when the outcome was recorded.

Kubernetes status, Events, policy audit records, and Git history may contribute to this
evidence. Ephemeral runner logs alone are insufficient.

## Security and agent boundary

The operation surface is semantic and allow-listed. Executors receive the least
privilege required for the submitted operation, prefer short-lived credentials, and
must not expose a permanently mounted cluster-admin kubeconfig as the consumer-facing
interface. Policy decisions and mutations must be auditable.

The operation API MUST NOT contain a generic command, script, shell, Helm-arguments, or
arbitrary-manifest endpoint. Each operation has a typed schema, explicit authorization
rule, bounded target scope, and dedicated audit identity. Conformance includes negative
RBAC tests proving that an Executor cannot mutate resources outside its operation scope,
read unrelated Secrets, bypass the policy decision point, or use expired credentials.
Any required management-cluster credential must be short-lived or narrowly scoped and
rotatable; a permanently reusable cluster-admin kubeconfig is non-conforming even when
hidden behind an API service.

This ADR does **not** authorize write-capable AI agents. ADR-Platform-015 keeps agents
read-only and requires a separate ADR for write access. Agents may draft contract
changes under the current model; a future write-capable agent could invoke the same
semantic operation surface only after that separate governance decision.

## Rationale

1. **Separates architecture from packaging.** A Docker runner, controller, Job, or CLI
   can implement Contract Execution without becoming the platform contract.
2. **Makes failure resumable.** Reconciliation and status survive Executor failure;
   the outcome is not coupled to a shell session.
3. **Resolves the CNI dependency boundary.** Cluster Enablement explicitly owns the
   minimum viable state required before normal GitOps.
4. **Preserves one source of truth.** Operations transition the declarative contract
   instead of creating parallel workflow state.
5. **Creates deterministic observability.** Generation-aware Conditions distinguish
   current readiness from stale success.
6. **Constrains automation.** Humans, CI, and future authorized agents consume the same
   semantic, policy-gated operations instead of privileged shells.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Keep the v4.2 runner as the lifecycle state machine | Couples readiness and recovery to a procedural process and retains direct post-provision mutation as the target model |
| Treat the runner as stateless | Factually inaccurate: it may hold rendered artifacts, kubeconfigs, checkpoints, and transient bootstrap state; `non-authoritative` is the required property |
| Let GitOps install all components including the initial CNI | Creates a dependency cycle for in-cluster GitOps profiles and fails to name minimum cluster viability as a separate responsibility |
| Call the post-control-plane phase "Bootstrap" | Conflicts with CAPI `BootstrapConfig` and obscures the difference between node initialization and cluster enablement |
| Expose `kubectl`, Helm, and shell as the platform operation interface | Bypasses semantic validation and policy boundaries, broadens credentials, and weakens auditability |
| Implement each operation as an independent workflow | Creates multiple lifecycle truths and allows workflows to bypass the declarative contract |
| Define readiness as a set of booleans | Loses generation, reason, message, and transition-time semantics and cannot reliably identify stale status |

## Consequences

**Positive:**

- The v4.2 runner has a precise evolutionary target: a thin, non-authoritative Contract
  Executor rather than a generic installation-script container.
- Cluster readiness becomes profile-aware, generation-aware, and machine-observable.
- Infrastructure, Enablement, and Platform failures can be distinguished and handled by
  their owning reconcilers.
- CLI, CI, API, GitOps, and future authorized automation can share one operation model.
- Provider implementations remain replaceable behind contracts and profiles.

**Negative / trade-offs:**

- A Cluster Enablement reconciler and normalized Condition surface must be designed,
  implemented, and operated.
- The transition from direct CNI installation to controller-driven Enablement adds a
  migration phase and may temporarily leave two paths in service.
- Durable operation evidence and policy decision records add storage, retention, and
  privacy requirements.
- Profile-dependent readiness is more precise but requires explicit profile schemas and
  conformance tests.

**Neutral:**

- This ADR does not select Crossplane, Argo CD, Flux, a CAPI add-on provider, or a
  specific policy engine.
- It does not create a new `ok-runner` repository. ADR-Platform-004's repository
  placement decision remains in force.
- It does not change the ok-infra/ok-mgmt responsibility split in ADR-Platform-007.
- It does not accept the illustrative `OpenKubesCluster` schema as a stable API.

## Acceptance conditions

Before this ADR moves to `Accepted`, a focused implementation spike must identify the
first concrete profile and produce reviewable evidence for all of the following:

1. **Single authority:** the authoritative persistence path for the first
   `OpenKubesCluster` contract is declared, and no Executor, Job, rendered artifact, or
   workflow record acts as a second source of truth.
2. **Policy and identity:** the policy decision point, requester identity, Executor
   identity, and their propagation into durable evidence are demonstrated.
3. **Forcing workflow:** at least one real KubeVirt workflow executes `CreateCluster`
   through the Contract path, reaches current-generation `InfrastructureReady`,
   `ControlPlaneReady`, `NetworkReady`, `EnablementReady`, and `PlatformReady`, and
   records the resulting operation evidence.
4. **Enablement ownership:** the first Cluster Enablement profile publishes its resource
   ownership set, its Enablement/Platform boundary, and a continuously reconciled CNI
   health and version contract.
5. **Single-writer status:** the normalized Condition schema and Status Aggregator prove
   that no two controllers write the same aggregate Condition and that `Ready` is only
   derived.
6. **Generation correctness:** stale-generation success is rejected; a new spec
   generation returns required Conditions to `Unknown`/reconciling until source
   observations for that generation converge.
7. **Failure and resume:** termination and restart of the Executor after acceptance of
   desired state neither blocks reconciliation nor loses the ability to observe the
   outcome.
8. **Deletion:** deletion exercises controller finalizers, infrastructure cleanup,
   declared retention/orphan policy, credential cleanup, and terminal evidence that
   survives removal of the cluster object.
9. **Security:** typed-operation enforcement, negative RBAC tests, policy-bypass denial,
   credential expiry/rotation, and absence of a generic command endpoint or reusable
   cluster-admin kubeconfig are demonstrated.
10. **Lifecycle conformance:** Create, Scale, Upgrade, Delete, retry, duplicate
    submission, partial Enablement failure, timeout, and recovery tests use Conditions
    rather than Executor exit status as their success oracle.
11. **Migration:** the boundary and rollback plan from the v4.2 direct CNI/Multus path
    are documented.

Acceptance explicitly requires the two hard lifecycle invariants stated in the Decision
section. A design review without the forcing-workflow and failure-path evidence is not
sufficient to move this ADR from `Proposed` to `Accepted`.

## Re-evaluation triggers

- A supported lifecycle implementation does not use CAPI and cannot map cleanly to the
  Infrastructure / Cluster Lifecycle Conditions.
- A CNI or other minimum-viability component can be proven to converge entirely through
  the selected GitOps profile without a distinct Enablement responsibility.
- A profile requires replacement or migration of CNI, CSI, or cloud integration after
  initial Enablement and reveals an ownership conflict with Platform reconciliation.
- A future write-capable agent ADR changes the authorization or identity model.
- Multiple authoritative persistence paths are required for disconnected Constraint
  Envelopes and cannot preserve a single desired-state authority.
