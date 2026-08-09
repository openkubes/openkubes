# Enablement E and NetworkReady Mechanism Evaluation

**Ticket:** OK-141

**Baseline:** `main` at `bf576c8`

**Input:** [enablement-network-ready-observation.md](enablement-network-ready-observation.md)

**Evaluation date:** 2026-08-09

**Infrastructure mutation:** `NO-GO`

## Question

Can an existing mechanism own the desired enablement revision and continuously
prove `NetworkReady`, or does this require genuinely new OpenKubes-owned
reconciliation?

## Result

```text
Semantic E construction                    Deterministic mechanism sufficient
Current procedural Helm path               Insufficient as durable owner
Desired E install/upgrade convergence       Existing mechanism configurable
Network runtime source signals              Existing mechanisms sufficient
Durable current NetworkReady proof          Still unresolved

Overall Enablement E / NetworkReady         Still unresolved
RequiresReconciler                          none proven
A/B/C/D                                     unclassified
```

The result is deliberately split. Existing add-on mechanisms can own the desired
Helm release without a new OpenKubes controller. None of the evaluated mechanisms
alone turns successful package reconciliation into a functional, revision-current
`NetworkReady` proof.

## Candidate semantic revision E

`E` can be a deterministic digest of versioned semantic inputs rather than a new
mutable database record:

```text
canonicalization profile
+ enablement profile identity/version
+ chart artifact digest
+ normalized Helm values
+ supported Kubernetes/provider/OS constraints
+ declared probe contract
-> SHA-256 E
```

Helm's release revision must not be used as `E`; it counts release operations and
does not establish semantic identity. Constructing and validating `E` is a
versioned function, not reconciliation.

## Mechanism assessment

### Current Helm CLI path

**Assessment:** insufficient as durable owner.

It provides deterministic submission and can wait for an immediate outcome. It
does not continuously compare the installed release with the reviewed repository
input after the process exits. Helm metadata is useful observed evidence but is
not a running control loop.

### ClusterResourceSet with `Reconcile`

Cluster API documents ClusterResourceSet as a basic mechanism for automatically
applying resources such as CNI/CSI to matching Clusters. The `Reconcile` strategy
reapplies changed referenced resources.

**Assessment:** configurable bootstrap primitive, but insufficiently expressive
as the preferred Cilium lifecycle mechanism without further evidence.

Strengths:

- already part of the installed CAPI core;
- can start after the workload API becomes reachable, before normal workload
  scheduling is viable;
- continuously applies versioned ConfigMap/Secret content with the `Reconcile`
  strategy;
- exposes ClusterResourceSetBinding application state.

Limits:

- CAPI calls it a basic solution and recommends an add-on provider for advanced
  lifecycle cases;
- it applies rendered Kubernetes resources rather than owning Helm chart,
  values, release, upgrade, and rollback semantics;
- deleting a ClusterResourceSet does not delete its managed workload resources;
- successful apply is not functional `NetworkReady`.

Reference: [ClusterResourceSet documentation](https://main.cluster-api.sigs.k8s.io/tasks/cluster-resource-set)

### Cluster API Add-on Provider for Helm

The upstream Cluster API Add-on Provider for Helm (CAAPH) is designed to manage
installation, configuration, upgrade, and deletion of Cluster add-ons from the
management cluster. Its `HelmChartProxy` declares repository, chart, version,
values, and target Cluster selection. A per-Cluster `HelmReleaseProxy` maintains
inventory, installs/upgrades/deletes the release, and exposes conditions, status,
and Helm revision.

The current upstream `v0.6.4` release is based on CAPI `v1.13`, matching the
observed CAPI generation closely enough to justify read-only feasibility review;
compatibility still requires a tested matrix before installation.

**Assessment:** existing mechanism configurable for desired `E` installation and
continuous Helm-release convergence.

It supplies the missing durable package control loop without creating an
OpenKubes-owned reconciler. An OpenKubes contract could select a reviewed profile
whose authoritative server-side projection creates or updates the existing
provider's desired resource. OpenKubes must not implement a second Helm
reconciler.

Before selection, a disposable test must prove:

- immutable/offline chart artifact identity, preferably through a reviewed OCI
  registry and non-mutable reference;
- normalized values identity and correlation to `E`;
- creation before Nodes become Ready and recovery after management/controller
  restart;
- upgrade, failure, retry, deletion, and credential behavior;
- generation-aware conditions for the selected Cluster and current desired spec.

References:

- [CAAPH project](https://github.com/kubernetes-sigs/cluster-api-addon-provider-helm)
- [CAAPH quick start and status model](https://github.com/kubernetes-sigs/cluster-api-addon-provider-helm/blob/main/docs/quick-start.md)

### Central Argo CD

The installed Argo CD instance demonstrates a general GitOps reconciler, but no
`ok-ai` registration or Cilium Application was observed.

**Assessment:** conceptually configurable, not currently evidenced for bootstrap
enablement.

A management-side Argo controller could avoid an in-cluster GitOps-agent CNI
dependency, but cluster registration, credential lifecycle, ordering, and
security boundaries would need proof. Argo Sync/Health would still not by itself
prove Node networking and functional data paths. This evaluation therefore does
not select Argo CD for `E`.

### Cilium runtime controllers

**Assessment:** existing mechanisms sufficient for Cilium-internal convergence
and runtime health sources, but not for desired profile ownership.

Cilium agents and operator continuously maintain datapath and internal state and
publish strong signals such as agent readiness and `CiliumIsUp`. They cannot
recreate the entire reviewed Helm release or prove which OpenKubes semantic
revision requested it.

## NetworkReady acceptance model

A strong `NetworkReady=True` should require all of the following for current `E`:

```text
desired E root is current
AND add-on release condition is Ready for E
AND required Cilium objects observed their current generations
AND required agents are updated, available, and ready
AND required operator components are available
AND every expected Node reports NetworkUnavailable=False/CiliumIsUp
AND every expected Node is Ready
AND profile-defined functional probes pass
AND evidence timestamps and Cluster identity are current
```

The functional probe contract should cover only minimum network viability, for
example DNS/service resolution and profile-relevant cross-node connectivity. It
must define sensor placement and failure domain so that a network failure cannot
silence the only observer and accidentally preserve `True`.

Package-manager Ready is one input to this rule, not its result.

## Reconciler necessity test

### Desired E and package convergence

1. **OpenKubes-specific desired state:** the profile choice is OpenKubes policy,
   but the Helm release desired state is standard add-on-provider semantics.
2. **Can it drift:** yes; release resources, chart version, and values can drift.
3. **Does drift matter:** yes; CNI is required for cluster viability.
4. **Continuous detection:** yes.
5. **Repeated correction:** yes.
6. **Existing authoritative controller:** yes; CAAPH is a concrete existing
   candidate, while CRS provides a simpler built-in alternative.
7. **Deterministic operation/evaluator sufficient:** not for correction, but an
   existing add-on controller is sufficient in principle.
8. **Duplicate ownership risk:** high if OpenKubes also performs Helm correction.

**RequiresReconciler:** `No` for a new OpenKubes-owned package lifecycle loop.

### NetworkReady proof

1. **OpenKubes-specific desired state:** the profile defines which source signals
   and probes are required.
2. **Can it drift:** yes; runtime networking can degrade after package success.
3. **Does drift matter:** yes.
4. **Continuous detection:** yes for operational truth; operation-completion
   evidence also needs a bounded current evaluation.
5. **Repeated correction:** the evaluator should not itself repair networking;
   correction belongs to the add-on and Cilium owners.
6. **Existing authoritative controllers:** multiple existing owners publish the
   source facts; no single durable aggregate source was observed.
7. **Deterministic evaluator sufficient:** possibly. On-demand evaluation is
   sufficient for executor outcome; continuous durable status may require a
   small aggregator/probe mechanism.
8. **Duplicate ownership risk:** low for a read-only evaluator, high if it starts
   mutating Cilium or Helm resources.

**RequiresReconciler:** `Unresolved`, not `Proven`.

If durable status is required, this is at most evidence toward outcome `B` until
it is shown that a new component must correct OpenKubes-owned state. A condition
aggregator is not a Cluster lifecycle owner.

## Why this does not prove an OpenKubes operator

The only proven corrective loop needed for `E` can be supplied by an existing
add-on provider. The remaining uncertainty is condition/probe ownership:

```text
CAAPH / CRS     -> converge declared package state
Cilium          -> reconcile networking internals
Kubernetes      -> publish object and Node conditions
probe/evaluator -> assess profile-defined NetworkReady
OpenKubes       -> normalize/present only if a forcing consumer requires it
```

No evidence requires OpenKubes to duplicate package or Cilium reconciliation.

## Next evidence

A later mutation-gated disposable test should compare, not preselect:

1. CAAPH with immutable Cilium artifact and values identity;
2. ClusterResourceSet `Reconcile` as the minimal baseline;
3. the existing procedural Helm path as the negative control for post-exit
   convergence.

It must inject controlled drift only after a separate GO and prove whether the
candidate restores exactly the current `E`. A separate probe test must show that
`NetworkReady` becomes false or unknown when a required runtime signal fails and
does not remain true because the observer was silenced.

Until then:

```text
Enablement E convergence:  Existing mechanism configurable
NetworkReady proof:        Still unresolved
RequiresReconciler:        none proven
A/B/C/D:                   unclassified
Infrastructure:            NO-GO
Failure Injection:         NO-GO
```
