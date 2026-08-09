# Allocation Authority Observation

**Ticket:** OK-141

**Baseline:** `main` at `0ef9995`

**Observation date:** 2026-08-09

**Mode:** read-only

**Infrastructure mutation:** `NO-GO`

**Failure injection:** `NO-GO`

This document records current allocation behavior without selecting a future
component or API. It separates control-plane endpoint addresses from Pod and
Service CIDR blocks because they have different writers and persistence models.

## Sensors

Repository observations used `rg` and read-only file inspection in:

- `ok-cluster/render.py` and `ok-cluster/new-cluster.sh`;
- `ok-cluster/templates/flatcar/cluster-v2.yaml.tpl`;
- `ok-cluster/templates/talos/providers/kubevirt/cluster-base.yaml.tpl`;
- `openkubes/platform/cluster-management/crossplane/`.

Live observations used only `kubectl get` and `kubectl api-resources` with:

- `~/.kube/ok-mgmt.yaml`;
- `~/.kube/ok-infra.yaml`.

No resource was created, patched, deleted, restarted, or otherwise mutated.

## Current local selection behavior

`ok-cluster/render.py` discovers checked-out `cluster-config.yaml` files and
selects the first unused value from fixed ranges:

| Value | Range | Selection inputs |
|---|---|---|
| control-plane endpoint | `192.168.100.200-192.168.100.254` | local endpoint declarations plus live `LoadBalancer` Service assignments |
| Pod CIDR | subnets `/16` from `10.32.0.0/11` | local config files only |
| Service CIDR | subnets `/20` from `10.96.0.0/12` | local config files only |

Endpoint selection queries all Services on `ok-infra`. If the API cannot be
reached, the renderer falls back to local files and prints a warning. Pod and
Service CIDR selection has no live observer.

The selection and subsequent manifest application are separate operations.
There is no lock, compare-and-swap, claim object, reservation UID, or atomic
commit covering selection and publication. Two concurrent renderers can
therefore select the same currently free value. Explicit endpoint collisions
known at render time fail closed, but the check does not reserve the value.

CIDR comparison uses exact strings from local files. It does not test arbitrary
CIDR overlap, and it cannot see clusters absent from the current checkout.

## Installed APIs and controllers

Both observed Kubernetes APIs expose the generic Cluster API IPAM contract
resources:

```text
ipaddressclaims.ipam.cluster.x-k8s.io
ipaddresses.ipam.cluster.x-k8s.io
```

No `IPAddressClaim` or `IPAddress` existed on either observed API. Neither API
exposed an `InClusterIPPool`/`GlobalInClusterIPPool`, and no IPAM provider
controller was present in the observed Deployment inventory. The generic CRDs
therefore prove API availability only; they do not prove an installed allocation
authority.

`ok-infra` contained:

- MetalLB controller `v0.14.9`;
- `IPAddressPool/metallb-system/ok-pool` with
  `192.168.100.200-192.168.100.254` and `autoAssign: true`;
- CAPK controller `v0.11.2`;
- CAPI controller `v1.13.3`.

`ok-mgmt` contained CAPI/CAPK and the generic IPAM contract CRDs, but no CAPI
Clusters, OpenKubes KubeVirtClusterClaims, IPAddressClaims, or IPAddresses at the
time of observation. This observation does not by itself classify lifecycle
authority or orphan status.

## KubeVirt endpoint authority chain

For `ok-ai`, live objects showed:

```text
KubevirtCluster/ok-ai
  spec.controlPlaneServiceTemplate.spec.type = LoadBalancer
        |
        v
Service/ok-ai-lb
  annotation metallb.io/ip-allocated-from-pool = ok-pool
  status.loadBalancer.ingress[0].ip = 192.168.100.201
        |
        v
KubevirtCluster/ok-ai
  spec.controlPlaneEndpoint.host = 192.168.100.201
        |
        v
Cluster/ok-ai
  spec.controlPlaneEndpoint.host = 192.168.100.201
```

The original applied Talos manifests omitted `controlPlaneEndpoint` and did not
request a fixed Service IP. The endpoint appeared later in managed fields owned
by a controller manager. This positively demonstrates a controller-driven
runtime allocation and projection path. It does not demonstrate correlation to
the endpoint value predicted earlier by the local renderer.

The Flatcar template differs: it places the selected endpoint in the
`metallb.universe.tf/loadBalancerIPs` annotation of the CAPK control-plane
Service template. MetalLB remains the component that accepts or rejects and
persists the Service allocation, but the requested value originates in local
selection.

## Live value correspondence

At observation time, the CAPI control-plane endpoint matched the corresponding
`<cluster>-lb` Service address for all listed clusters. Examples included:

| Cluster | CAPI endpoint | MetalLB Service address |
|---|---:|---:|
| `ok-mgmt` | `192.168.100.200` | `192.168.100.200` |
| `ok-ai` | `192.168.100.201` | `192.168.100.201` |
| `ok-robotics` | `192.168.100.204` | `192.168.100.204` |
| `ok-shared` | `192.168.100.206` | `192.168.100.206` |
| `ok-iot` | `192.168.100.212` | `192.168.100.212` |

The same MetalLB pool also served non-control-plane Services. Allocation scope is
therefore the complete pool and all eligible Services, not only OpenKubes
Clusters.

## Live CIDR observation

CAPI carried Pod and Service CIDRs, but no allocation claim, pool reference,
allocation UID, or authoritative reservation was observed for them.

Multiple live, isolated clusters used the same values:

| Cluster | Pod CIDR | Service CIDR |
|---|---|---|
| `ok-iot` | `10.36.0.0/16` | `10.96.64.0/20` |
| `ok-kagent` | `10.36.0.0/16` | `10.96.64.0/20` |
| `ok-obs-verify` | `10.36.0.0/16` | `10.96.64.0/20` |

This is not evidence of a defect by itself. Reuse can be valid while clusters
are network-isolated. It is evidence that global CIDR uniqueness is neither a
declared nor an enforced invariant in the observed system.

## Raw factual conclusions

1. `next-ip` and next-CIDR logic is deterministic selection, not durable
   allocation authority.
2. MetalLB is an observed, persistent runtime authority for LoadBalancer Service
   addresses on `ok-infra`.
3. CAPK projects the allocated KubeVirt control-plane endpoint into infrastructure
   and CAPI Cluster objects.
4. No active CAPI IPAM provider or IPAM claims were observed.
5. No durable Pod-/Service-CIDR allocation authority was observed.
6. The required CIDR uniqueness scope is not currently defined by evidence.
