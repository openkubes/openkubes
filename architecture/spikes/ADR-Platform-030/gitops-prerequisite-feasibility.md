# T2b — GitOps Prerequisite Feasibility

**Ticket:** OK-141

**Baseline:** `main` at `948e860`

**Evaluation date:** 2026-08-09

**Infrastructure mutation:** `NO-GO`

**Failure injection:** `NO-GO`

## Question

Can an existing GitOps mechanism carry the bound `P'` with unambiguous target
identity, immutable source revision, continuing convergence, and defensible
`PlatformReady` evidence without introducing new OpenKubes-owned
reconciliation?

## Bound input

```text
P'                       sha256:b46911c06ac31ed4755ffa83b0c960fafa0a23cab8442dc9eb1945df927b0665
FixtureDigest'           sha256:b27bb7c8e959e2c1028fcc0822755caa795ce21432344a64a62474abeb7f9f2b
Application-set digest   sha256:60f95393486bdb2276d4e7af1aadc57e17eb722b340e1bc0351295f3f5e53c18
Source commit            fe394da8875adecc3b497137e546cecabd710d1d
Required Applications    1
```

T2b does not change these values or reinterpret the historical Phase-R-v2
fixture. Newly discovered operational inputs remain blockers until a later
fixture/protocol explicitly binds them.

## Result

```text
GitOps implementation capability          Existing Argo mechanism configurable
GitOps control-plane placement             ok-shared candidate; authority unresolved
Authoritative fixture root                 Direct Application selected
App-of-Apps / ApplicationSet               Not required by this fixture
Immutable desired Git revision             Available: exact commit
Exact Application membership               Offline proven
P' convergence                             Not execution-proven
Native target addressing                   Configurable by name/server
Immutable target identity                  Unresolved; external proof required
AppProject least-privilege policy          Shape defined; rendered inventory missing
PlatformReady proof model                  Offline complete
Platform capability materialization        Unresolved
OpenKubes platform reconciler              Not required

T2b overall                                Configurable with blocking prerequisites
M0b                                        NOT GRANTED
GO-1                                      NOT GRANTED
```

The mechanism can own platform convergence. The blockers are placement
authority, registration/credential identity, exact materialization of the
selected capability, and execution evidence—not missing OpenKubes GitOps
reconciliation.

## Placement boundary

`ok-shared` remains the recommended datacenter candidate because it separates
platform convergence from the Tier-0 CAPI lifecycle plane. It is not an
authorized placement:

- ADR-020 makes `ok-shared` plausible for shared platform services but does not
  authorize a cross-Cluster GitOps writer;
- the observed Cluster still has one control-plane/etcd member;
- capacity, controller-to-target network reachability, credential recovery,
  backup/restore, and blast-radius controls remain unproven; and
- Argo must be recoverable without depending on its own successful
  reconciliation.

No Argo object is installed on or submitted to `ok-shared` by T2b. A later M0b
must bind a reviewed placement decision and exact controller release/image
identities before any installation can be considered.

See [ok-shared-gitops-placement-feasibility.md](ok-shared-gitops-placement-feasibility.md).

## Authoritative root selection

T2b selects a direct `Application` model for this fixture:

```text
OpenKubes profile minimal-observability-v2
        │ exact membership = 1
        ▼
Application disposable-ok141-observability
        │ exact Git commit
        ▼
workload Cluster / observability namespace
```

The semantic OpenKubes profile remains the definition of `P'`. The direct
Application is the single Argo desired-state unit for its one required leaf.

App-of-Apps is rejected for this fixture because no transitive composition is
needed and a parent Application's health is not automatic child readiness.
ApplicationSet is rejected because no multi-Cluster or parameterized generation
consumer exists. Creating either component would add an ownership and evidence
surface without satisfying a forcing requirement.

The exact decision is recorded in
[`harness/candidates/argocd-gitops-v1/root-model.json`](harness/candidates/argocd-gitops-v1/root-model.json).

References:

- [Argo declarative Applications](https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/#applications)
- [Argo resource-health boundary](https://argo-cd.readthedocs.io/en/stable/operator-manual/health/)

## Application and source identity

The frozen Application already uses the strongest Git revision form supported by
the profile:

```text
repoURL        https://github.com/openkubes/ok-observability.git
path           profiles/ok-observability-standard
targetRevision fe394da8875adecc3b497137e546cecabd710d1d
```

The commit exists in the local authoritative `ok-observability` history and the
profile path exists at that commit. Branch, tag, or `HEAD` substitutions are not
accepted as applied identity.

For `PlatformReady`, the current Application must prove all of the following:

```text
current normalized spec equals the fixture Application
AND status.sync.comparedTo corresponds to that source and destination
AND status.sync.revision equals the exact commit
AND status.sync.status == Synced
AND status.health.status == Healthy
AND no current comparison/spec/sync error exists
```

A historical successful operation is never a replacement for current comparison
and sync evidence.

References:

- [Argo Application specification](https://argo-cd.readthedocs.io/en/stable/user-guide/application-specification/)
- [Argo automated sync, self-heal, and retry](https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/)

## Target registration identity

Argo declaratively registers a Cluster through a Secret labelled
`argocd.argoproj.io/secret-type: cluster`. Its native identity inputs are mainly
the registration name, API server URL, and credential/TLS configuration.
Applications may target the registration by `destination.name`.

Neither the name nor the API URL is immutable workload identity:

```text
registration name reused
or API endpoint reused
does not prove
same CAPI Cluster incarnation
```

T2b therefore defines this correlation chain:

```text
Application destination.name
  -> exactly one current registration Secret
  -> registration Secret UID
  -> annotated current CAPI Cluster UID
  -> live workload kube-system Namespace UID
  -> workload API CA fingerprint
  -> independently observed current API endpoint
```

The full chain must be captured in the M0b/GO-1 evidence. The registration
Secret's OpenKubes annotations carry correlation claims; Argo does not enforce
them. A bounded evaluator must compare them with independent CAPI and workload
observations and fail closed on mismatch.

The metadata-only candidate at
[`harness/candidates/argocd-gitops-v1/cluster-registration-metadata-candidate.yaml`](harness/candidates/argocd-gitops-v1/cluster-registration-metadata-candidate.yaml)
uses `https://api.invalid`, omits `config`, and contains `M0B_REQUIRED`
sentinels. It is deliberately non-operational and contains no credential.

Before M0b, the registration model must bind:

1. exact live target identities above;
2. a least-privilege, rotatable authentication mechanism;
3. TLS CA verification without `insecure` bypass;
4. allowed namespaces and required cluster-scoped permissions;
5. credential creation, rotation, revocation, backup, and recovery authority;
6. independent redacted evidence that never retains token/key material.

References:

- [Argo declarative Cluster Secrets](https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/#clusters)
- [Argo Cluster management](https://argo-cd.readthedocs.io/en/stable/operator-manual/cluster-management/)

## AppProject boundary

The candidate AppProject restricts the repository and target registration/
namespace. It intentionally grants no cluster-scoped resource kind because the
exact rendered inventory has not been retained.

That candidate is at
[`harness/candidates/argocd-gitops-v1/appproject-candidate.yaml`](harness/candidates/argocd-gitops-v1/appproject-candidate.yaml)
and is marked `blocked-no-go`.

M0b must render the exact pinned source using the selected Argo version and
configuration-management behavior, retain the output digest/inventory, and then
derive both:

- the AppProject resource allow-list; and
- the workload service-account RBAC.

Wildcards are not accepted merely to make the first sync pass. The `default`
AppProject is also not acceptable because it is permissive by default.

References:

- [Argo Projects](https://argo-cd.readthedocs.io/en/stable/user-guide/projects/)
- [AppProject specification](https://argo-cd.readthedocs.io/en/stable/operator-manual/project-specification/)

## P' materialization blockers

The exact source commit exposes gaps that the earlier semantic fixture did not
resolve operationally.

### Provider Values

The selected chart's own documentation says a real cluster-specific Provider
Values file is expected to be layered over its defaults. The frozen Application
declares no Helm values or values file. The selected StorageClass, credentials,
retention/resources, ingress/access configuration, and alert receiver are
therefore not bound by the current Application.

### Namespace preconditions

The source documentation requires a privileged Pod Security Admission namespace
for node-exporter and Fluent Bit. The frozen destination is `observability`,
while the capability Contract Test defaults to `ok-observability`. The
Application neither creates/labels the namespace nor declares an override for the
Contract Test.

### Source membership

The Git path contains the composed Helm chart, but its documentation also applies
alerting rules and dashboards from repository paths outside that chart. The
single frozen Application does not prove that those additional manifests are
part of its rendered desired state.

### Sync defaults

Prune and self-heal are explicit. Automated `enabled`, retry/backoff,
allow-empty behavior, sync options, and namespace creation are not explicit.
Those behaviors depend on the selected controller/API defaults unless a later
candidate binds them.

These are not arguments for an OpenKubes reconciler. They mean only that `P'`
cannot yet be executed as a complete platform profile. Before M0b, one of two
paths must be reviewed:

```text
A. prove the current frozen Application is complete under an exact Argo version
or
B. supersede the Application/fixture with explicit provider values, membership,
   namespace policy, and sync semantics, then recompute affected digests
```

T2b must not silently choose B because that would rewrite the merged Phase-R-v2
experiment.

## PlatformReady proof chain

The offline acceptance model is stored at
[`harness/candidates/argocd-gitops-v1/platformready-assertion.json`](harness/candidates/argocd-gitops-v1/platformready-assertion.json).

For current `P'`, `PlatformReady=True` requires:

```text
exact direct-Application membership
AND immutable target correlation chain passes
AND current Application spec and comparedTo correlate
AND exact commit is the current applied revision
AND Sync == Synced
AND Health == Healthy
AND no current invalidating Condition/operation exists
AND every profile-required capability check has current passing evidence
AND all retained artifacts verify against the evidence bundle
```

Argo Health is authoritative for the health model it computes from immediate
managed resources. It is not the entire OpenKubes capability contract. The
capability-owned checks remain separate required evidence.

The evaluator observes and correlates only. It must not sync the Application,
modify the registration, or repair platform resources.

## Convergence and failure semantics

With automated sync, prune, and self-heal configured, Argo owns desired/live
comparison and correction for its managed resource set. Retry behavior can be
configured in the Application sync policy and must be explicit or bound to a
specific selected version before execution.

```text
Git/source or live-resource drift   Argo Application controller
capability runtime internals        capability controllers
target identity correlation        bounded evaluator/evidence
PlatformReady                       bounded evaluator
OpenKubes executor                  submit/observe/collect only
```

Argo outage pauses convergence. It does not authorize the Executor or another
controller to become a replacement GitOps writer.

## M0b prerequisites

A later separately authorized M0b can be proposed only after these values are
exact and reviewed:

1. accepted placement authority for `ok-shared` or another selected plane;
2. exact Argo release, image digests, install manifest digest, namespace, and HA
   profile;
3. bootstrap/recovery path independent of Argo itself;
4. measured capacity and declared availability/recovery objectives;
5. Pod-originated network/TLS reachability to Git and the workload API;
6. complete target-registration identity and credential lifecycle;
7. exact rendered source inventory and least-privilege AppProject/workload RBAC;
8. resolution of provider values, namespace policy, source membership, and sync
   defaults;
9. positive/negative observations, stop conditions, rollback, and evidence
   destination;
10. a new canonical protocol digest covering every chosen value.

Preparing or reviewing M0b grants no mutation authority.

## Reconciler necessity result

Argo supplies the platform corrective loop. OpenKubes supplies deterministic
`P'` construction, authorized submission, target/revision correlation, and
bounded evaluation.

```text
OpenKubes GitOps lifecycle loop required   No
Existing Argo mechanism sufficient today  Not proven
Existing Argo mechanism configurable      Yes, with blockers
RequiresReconciler                         none proven
```

An OpenKubes component that directly repairs Argo-managed platform resources or
runs a competing package workflow would duplicate GitOps ownership and cross the
outcome-D reject boundary.

## Operational state

```text
T1                   complete on main
T2a                  complete on main
T2b                  read-only feasibility complete locally
T3                   not started
M0b                  NOT GRANTED
GO-1                 NOT GRANTED
Infrastructure       NO-GO
Failure Injection    NO-GO
```
