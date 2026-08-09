# Platform P and PlatformReady Observation

**Ticket:** OK-141

**Baseline:** `main` at `bc34e65`

**Observation date:** 2026-08-09

**Infrastructure mutation:** `NO-GO`

## Scope

This document records the OpenKubes GitOps gap and a separate, non-authoritative Argo
CD behavior sample before a mechanism is selected. It does not define a public
OpenKubes API, install a GitOps controller, register a workload Cluster, or mutate an
Application.

Read-only sensors used:

- repository inventory and ADR-011;
- `/Users/arash/.kube/ok-infra.yaml`;
- `/Users/arash/.kube/ok-mgmt.yaml`;
- `/Users/arash/.kube/ok-ai.yaml`;
- Argo CD `Application`, `ApplicationSet`, controller workload, and cluster-secret
  metadata on `ok-infra`.

No Secret data, repository credential, rendered manifest, or token was retained.

## Ownership boundary correction

The Argo CD installation on `ok-infra` belongs to an unrelated test project. It is not
part of OpenKubes, is not intended to reconcile OpenKubes Clusters, and must not be
treated as:

- an OpenKubes GitOps control plane;
- a candidate placement decision for the future OpenKubes GitOps profile;
- an authority for `P` or `PlatformReady`;
- evidence that OpenKubes already has a configured GitOps mechanism; or
- permission to reuse or modify that installation.

Its Application metadata is retained only as an external read-only behavior sample for
status semantics and negative controls. OpenKubes mechanism conclusions must come from
the repository contract, upstream controller capabilities, and a later explicitly
authorized OpenKubes forcing profile.

## Repository observation

ADR-011 proposes Argo CD and an App-of-Apps profile, with one root Application per
Cluster namespace and child Applications for platform capabilities. The implementation
material under `platform/gitops/` is still placeholder documentation:

- there is no implemented `ok-gitops` repository in the reviewed workspace;
- there is no declared OpenKubes platform-profile root;
- there is no deterministic membership rule for required platform Applications;
- there is no current `P` construction rule; and
- there is no `PlatformReady` publisher.

The proposal is therefore useful architecture input, not current runtime proof.

## Current OpenKubes delivery paths

The current `ok-cluster` workflow exposes separate imperative targets rather than one
platform profile:

| Capability/action | Current submission path | Desired revision behavior | Durable convergence/status |
|---|---|---|---|
| CNI | `make install-cni` / Helm | chart/version logic belongs to Enablement `E` | evaluated in the Enablement follow-up |
| workload-local storage | `make install-storage` / remote manifest plus patches | manifest URL version is explicit; no common `P` | no GitOps owner |
| ingress | `make install-ingress` / Helm plus host Service apply | chart repository is used procedurally; no common `P` | no GitOps owner |
| Vault Secrets Operator | `make install-vso` / version-pinned Helm | explicit chart version | no common platform root |
| observability | `make install-observability` | pinned `ok-observability` commit supported and required in pinned mode | immediate Helm/apply plus functional Contract Test; no continuous platform root |

The `ok-ai/cluster-config.yaml` value `upgrade.workloadMigration.stateless: gitops`
describes workload migration behavior. It is not a GitOps installation, platform
profile, desired revision, or readiness source.

`ok-observability` is the strongest current capability-level provenance precedent:

- pinned mode requires `OK_OBSERVABILITY_REF`;
- the ref is resolved to an immutable commit;
- only the materialized commit tree is consumed;
- the install runs a capability-owned functional Contract Test; and
- the process reports the consumed `ok-cluster` and `ok-observability` commits.

That evidence is process output. The reviewed workflow does not persist the consumed
commit and current Contract-Test result as a continuously refreshed Cluster-level
platform status. It is therefore a useful candidate leaf of `P`, not an existing `P`
root.

## Current ok-ai release inventory

A read-only `helm list -A` on `ok-ai` reported:

| Release | Namespace | Chart | Helm status | Layer observation |
|---|---|---|---|---|
| `cilium` | `kube-system` | `cilium-1.19.6` | `deployed` | Enablement, not Platform `P` |
| `traefik` | `ingress` | `traefik-41.0.2` | `deployed` | possible platform capability |
| `kagent` / `kagent-crds` | `kagent` | `0.9.9` | `deployed` | profile membership not declared |
| `platform-diagnostics-facade` | `platform-diagnostics` | `0.1.0` | `deployed` | possible platform capability; no declared root |
| `open-webui-ok-ai` | `open-webui` | `15.2.0` | `deployed` | Application layer unless a future profile explicitly requires it |
| `openclaw` | `openclaw` | `0.1.0` | `deployed` | Application layer unless a future profile explicitly requires it |

No `ok-observability-standard`, storage, or VSO Helm release appeared in this snapshot.
Absence from Helm does not prove capability absence because some mechanisms apply plain
resources, but it does prove that Helm inventory alone cannot define profile membership.

`helm status=deployed` is package-manager history, not functional readiness and not
desired provenance. The release revision counter records Helm operations rather than a
semantic OpenKubes revision.

The current runtime therefore has several individually installed capabilities and
applications but no durable statement answering:

```text
Which exact set is required by the selected platform profile?
Which immutable desired revision does each member represent?
Which current source proves each member's functional contract?
```

## Live GitOps placement

| Cluster | Argo CD API | Argo namespace | Platform-root observation |
|---|---:|---:|---|
| `ok-infra` | Present, unrelated test project | Present | Out of OpenKubes scope; never an OpenKubes platform root |
| `ok-mgmt` | Absent | Absent | No Argo source for platform status |
| `ok-shared` | Absent | Absent | Existing Shared Services Cluster; candidate datacenter placement, not implemented |
| `ok-ai` | Absent | Absent | No in-cluster Argo source for platform status |

Argo CD `v3.4.3` runs on `ok-infra` for the unrelated project. Its application,
ApplicationSet, repository, server, notifications, and Redis workloads were observed
available at the time of the snapshot. This proves only that the external test instance
runs; it is not OpenKubes capability evidence.

No `ApplicationSet` object was present. No Argo cluster-registration Secret metadata
was returned. Every observed Application targeted the local server
`https://kubernetes.default.svc`.

Consequently, OpenKubes has no observed Argo path to reconcile `ok-ai`. The unrelated
instance is excluded rather than considered an unconfigured OpenKubes candidate.

### ok-shared placement facts

`ok-shared` is the accepted Shared Platform Services capability and currently hosts
central services including Vault-related components and Keycloak assets. A read-only
snapshot showed:

- one Ready control-plane Node and three Ready worker Nodes;
- no `argoproj.io` API resources and no `argocd` namespace;
- `vault` and `vault-secrets-operator` namespaces; and
- a declared one-control-plane/three-worker Cluster shape in `ok-cluster`.

This makes `ok-shared` a plausible central datacenter GitOps placement, but not an
existing GitOps authority. Its current single control-plane replica and concentration of
shared services are availability and blast-radius inputs for a later implementation
spike, not permission to install Argo CD now.

## External Application behavior sample

The following objects belong to the unrelated project. They are not an OpenKubes
inventory and are used only to demonstrate how native Argo fields can disagree.

| Application | Desired source | Destination | Sync | Applied/status revision | Health | Current condition |
|---|---|---|---|---|---|---|
| `app-sync` | Git path at symbolic `main` | local `argocd` | `Unknown` | symbolic `main`; previous successful operation records commit `d7b4115...` | `Healthy` | repository authentication `ComparisonError` |
| `hivemq` | Helm `0.2.68` plus Git values at symbolic `main` | local `hivemq` | `Unknown` | current sync revision absent; previous operation records `[0.2.68, d7b4115...]` | `Healthy` | source-generation `ComparisonError` |
| `hivemq-operator` | Helm `0.2.23` | local `hivemq` | `OutOfSync` | `0.2.23` | `Healthy` | no Application condition; one managed CRD remained `OutOfSync` |

All three Applications enable automated prune and self-heal. Their state supplies a
strong negative control:

```text
Health=Healthy
does not imply
Sync=Synced, desired revision resolvable, or current desired state applied
```

The old successful operation records are historical evidence only. They cannot promote
the current Applications to Ready while current comparison is failing or current sync is
`Unknown`/`OutOfSync`.

## Desired versus applied revision observations

Argo exposes several different identities:

```text
spec.source.targetRevision / spec.sources[].targetRevision
    -> requested references; may be symbolic

status.sync.revision / status.sync.revisions
    -> revision(s) from the latest successful current comparison when available

status.operationState.syncResult.revision(s)
    -> revision(s) of a completed operation; may be historical

status.sync.comparedTo
    -> desired source and destination Argo compared
```

The live snapshot proves that these fields must not be conflated:

- `main` is a moving selector, not an immutable applied platform revision;
- a multi-source Application needs an ordered revision vector, not one scalar field;
- a historical successful `syncResult` can coexist with a current comparison error;
- application generation alone is not enough because no matching
  `status.observedGeneration` was exposed in the observed Application status; and
- `status.sync.comparedTo` must correspond to the current normalized source and
  destination before its sync result can be consumed.

## Root and membership observation

`app-sync` is an App-of-Apps-style parent for the two HiveMQ Applications, but it is not
an OpenKubes platform root:

- it is unrelated to `ok-ai`;
- it targets the local infrastructure Cluster;
- no OpenKubes platform-profile identity or contract revision was present;
- its own Health remained `Healthy` while its child resources had unknown sync status;
  and
- current source comparison failed.

The parent therefore cannot be treated as a transitive health aggregate. A future
profile must explicitly define the complete required Application set, either directly or
through a deterministic root/generator relationship.

## Raw observation classification

| Required capability | Existing observation | Classification |
|---|---|---|
| OpenKubes GitOps controller availability | No OpenKubes-owned/configured instance observed | Missing |
| Desired source declaration capability | Application source(s), destination, and sync policy demonstrated externally and documented upstream | Configurable |
| Applied immutable revision capability | Native revision field(s), but absent/stale during current errors and symbolic inputs exist | Configurable with fail-closed rules |
| Continuous drift correction capability | automated sync, prune, and self-heal documented upstream and demonstrated externally | Configurable |
| Per-Application sync/health capability | Native status and conditions demonstrated externally | Configurable |
| OpenKubes platform profile root | Not observed | Missing |
| `ok-ai` GitOps registration | Not observed | Missing |
| Required-Application membership | Not declared | Missing |
| Desired semantic platform revision `P` | Not declared | Missing |
| Durable `PlatformReady` | Not observed | Missing |
| Capability-level pinned provenance | `ok-observability` pinned install path | Available as procedural precedent, not current aggregate status |

`Missing` does not mean `RequiresReconciler`. The next artifact evaluates whether the
missing semantics can be supplied by deterministic profile construction and the existing
GitOps controller.

## Observation conclusion

```text
External Argo behavior sample    observable, not OpenKubes-owned
OpenKubes GitOps controller      not observed
OpenKubes desired state          not observed
OpenKubes platform profile       absent
ok-ai platform ownership         absent
Capability-level provenance      partially available, not aggregated
PlatformReady                    not derivable from the current snapshot
```

The most important live finding is:

> Argo CD can expose useful desired, applied, sync, health, and error facts, but the
> observed instance is unrelated to OpenKubes. OpenKubes has neither a platform root nor
> an authoritative GitOps status source for `ok-ai` today.
