# ok-shared Central GitOps Placement Feasibility

**Ticket:** OK-141

**Baseline:** `main` at `bc34e65`

**Evaluation date:** 2026-08-09

**Infrastructure mutation:** `NO-GO`

## Question

Is `ok-shared` a plausible central datacenter placement for the selected OpenKubes
GitOps controller, and what must be proven before installation?

## Result

```text
Datacenter placement direction       central on ok-shared recommended
ADR-020 compatibility                plausible, not sufficient authority
Explicit GitOps placement decision   required in ADR-011 or a focused amendment
Argo HA node geometry                available in principle (three workers)
ok-shared control-plane HA           absent (one control-plane/etcd member)
Capacity headroom                    unproven
Runtime metrics                      unavailable
Resource governance                 incomplete
Target API reachability              unproven from the controller failure domain
Credential/RBAC model                unproven
Install readiness                    NO-GO
```

This is a placement feasibility result, not an Argo CD installation plan.

## Contract alignment

ADR-020 accepts `ok-shared` as the dedicated Cluster for centrally operated Shared
Platform Services and explicitly keeps those services away from `ok-mgmt`. This supports
the failure-domain argument for a central GitOps service on `ok-shared`:

- a pure `ok-mgmt` outage need not stop platform convergence;
- lifecycle controllers remain isolated from application-facing shared services; and
- one centrally operated capability avoids N per-Cluster control-plane installations.

There is also a boundary that must not be hidden. ADR-020 says `ok-mgmt` controls
Clusters while `ok-shared` serves them. A GitOps controller actively converges platform
resources on other Clusters; it is a platform-convergence control service, not merely an
application endpoint. GitOps is not in ADR-020's accepted v1 service list.

Therefore:

> ADR-020 makes `ok-shared` a plausible home, but does not by itself authorize GitOps
> placement there.

The placement should be made explicit when ADR-011's implementation profile is accepted,
or through a narrowly scoped amendment. ADR-030 remains unchanged.

## Live ok-shared snapshot

### Nodes and control plane

| Role | Count | Per-Node allocatable CPU | Per-Node allocatable memory | Ready |
|---|---:|---:|---:|---:|
| control plane / etcd | 1 | `1950m` | about `3.2 GiB` | 1/1 |
| worker | 3 | `1950m` | about `3.3 GiB` | 3/3 |

All four Nodes were Ready. The three workers satisfy Argo CD's documented minimum node
geometry for its HA manifests, whose anti-affinity requires at least three different
Nodes. This does not make the Kubernetes API or etcd highly available: the Cluster still
has exactly one control-plane/etcd member.

Argo CD documents production HA as recommended and stores authoritative state as
Kubernetes objects in etcd; Redis is a disposable cache. On this Cluster, losing the one
control-plane/etcd member can therefore make the entire GitOps desired/status store
unavailable even when Argo workloads are spread over the workers.

References:

- [Argo CD installation profiles](https://argo-cd.readthedocs.io/en/stable/operator-manual/installation/)
- [Argo CD high availability](https://argo-cd.readthedocs.io/en/stable/operator-manual/high_availability/)

### Existing critical workloads

The snapshot included:

- three Vault server replicas, one on each worker;
- Keycloak and its CNPG database;
- Vault Secrets Operator;
- cert-manager and CNPG controllers;
- Traefik, Cilium, CoreDNS, and local-path provisioning.

One worker hosted Keycloak, its database, one Vault member, and both CoreDNS replicas at
the observation time. Existing scheduling is therefore not evenly failure-isolated for
all critical services.

### Storage and disruption

The only StorageClass was `local-path` with `Delete` reclaim policy and
`WaitForFirstConsumer`. Vault used three data and three audit PVCs; Keycloak used a
database PVC. The snapshot exposed a Vault PDB allowing one disruption and a Keycloak
database PDB allowing none. No broad PDB inventory demonstrated disruption protection
for every shared controller.

Argo CD does not need this local storage for its authoritative state when installed in
the standard model; Kubernetes objects/etcd are the authority. The local-storage finding
still matters because adding GitOps increases the criticality of a Cluster already
hosting stateful shared services whose recovery obligations must be coordinated.

### Capacity evidence

The Metrics API was unavailable, so current CPU and memory utilization could not be
measured. Several critical workloads, including Vault, Traefik, cert-manager, Cilium,
and the local-path provisioner, declared no resource requests or limits in the observed
Pods.

Scheduler-visible free capacity is therefore not reliable capacity evidence:

```text
allocatable - declared requests
!=
proven runtime headroom
```

No production Argo sizing decision is allowed from this snapshot.

### Network and security evidence

This read-only pass did not execute a Pod-originated connectivity probe from `ok-shared`
to workload API endpoints. Host-side API reachability is not equivalent to the Argo
controller's network path.

No OpenKubes Argo namespace, CRD, AppProject, cluster credential, or service account
exists on `ok-shared`. Consequently no least-privilege or credential-rotation claim is
currently testable.

## Placement benefits

If the gates below pass, central GitOps on `ok-shared` provides:

- platform convergence independent of a pure `ok-mgmt` outage;
- one controller fleet, policy surface, and upgrade path for datacenter Clusters;
- central correlation of `P`, Application revisions, and `PlatformReady` evidence;
- no full Argo installation overhead on each workload Cluster; and
- natural integration with centrally operated identity and secret capabilities without
  placing application-facing services on `ok-mgmt`.

## Placement risks

- `ok-shared` outage pauses platform convergence for every centrally managed Cluster.
- Compromised GitOps credentials can affect multiple workload Clusters.
- Argo increases the blast radius and recovery scope of an already critical shared
  Cluster.
- Co-location with Vault and identity introduces resource-contention and correlated
  maintenance risk.
- Self-management can create a recovery loop if the only installer/reconciler for Argo
  is the unavailable Argo instance.
- Managing `ok-shared` itself from the same Argo instance needs a separately proven
  bootstrap and break-glass boundary.

## GO requirements for a later implementation spike

Installation remains `NO-GO` until all of the following are verified:

1. ADR-011 or a focused amendment explicitly selects `ok-shared` for the datacenter
   GitOps profile.
2. The required availability objective is declared, and one-control-plane operation is
   either accepted with tested restore evidence or replaced by a proven HA control
   plane.
3. Runtime capacity is measured; every Argo component and existing critical workload
   has reviewed requests, limits, affinity, and disruption behavior.
4. Pod-originated network/TLS probes reach every forcing workload API and required
   Git/OCI endpoint.
5. Per-Cluster credentials are least-privilege, rotatable, recoverable, and scoped by
   AppProject/destination policy.
6. Backup and restore covers Argo CRs/configuration, repository and Cluster registration
   metadata, credentials, and the `R -> P` evidence chain.
7. The failure test proves that `ok-shared` outage pauses convergence without breaking
   existing workload runtime, and that restart creates no competing writer.
8. Bootstrap/recovery can reinstall Argo without depending on Argo.
9. Argo owns neither CAPI lifecycle nor the pre-network Enablement path.
10. The exact forcing profile, expected resource set, stop conditions, and rollback are
    checksum-bound under a new explicit GO.

> **The GitOps control plane must be recoverable without depending on its own successful
> reconciliation.**

## Classification

```text
Placement candidate:       Configurable
Current installation:      Missing
Capacity/HA evidence:      Insufficient
New OpenKubes reconciler:  Not required
Infrastructure:            NO-GO
Failure Injection:         NO-GO
```
