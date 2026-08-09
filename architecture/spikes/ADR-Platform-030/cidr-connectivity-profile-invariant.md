# CIDR and Connectivity Profile Invariant

Status: **Read-only R1 closure for the first disposable execution fixture**

Recorded: 2026-08-09

Ticket: OK-141

Baseline: `main` at `c4e3657`

## Question

Within what scope must Pod and Service CIDRs be unique, and does the first ADR-030
execution fixture require a persistent multi-cluster CIDR allocation authority?

This document defines a test-profile invariant. It does not create a public Contract,
select an IPAM product, or modify `ok-cluster`.

## Read-only evidence

### Current selection behavior

`ok-cluster/render.py` already contains deterministic first-free selection:

| Value | Candidate range | Unit | Observer |
|---|---|---|---|
| Pod CIDR | `10.32.0.0/11` | `/16` | checked-out `cluster-config.yaml` files only |
| Service CIDR | `10.96.0.0/12` | `/20` | checked-out `cluster-config.yaml` files only |

The implementation exposes `allocated_pod_cidrs`, `allocated_svc_cidrs`,
`next_free_pod_cidr`, and `next_free_svc_cidr`. It materializes selected values in the
local Cluster configuration before rendering CAPI resources.

This is a deterministic convenience function, not allocation authority:

- there is no lock or compare-and-swap;
- there is no claim/reservation UID;
- two concurrent or disconnected checkouts can select the same value;
- Clusters absent from the checkout are invisible;
- comparison tests exact strings rather than arbitrary CIDR overlap;
- there is no authoritative release transition; and
- Pod/Service selection has no live API observer.

The existing live observation also found isolated Clusters sharing CIDRs. That does
not prove a defect because global uniqueness has never been declared or enforced.

### Current connectivity behavior

The accepted datacenter paths expose Cluster services through explicit host-level
MetalLB/Ingress endpoints:

```text
client or another Cluster
  -> host-level LoadBalancer address on ok-infra
  -> KubeVirt/NodePort/Ingress path
  -> target workload Service/Pod
```

Examples include per-Cluster ingress and the central Vault endpoint. Workload Clusters
may have stable connectivity to these services while their Pod and Service address
spaces remain unexported and mutually unrouted.

No reviewed evidence shows direct route exchange, a shared pod-routing domain, Service
CIDR export, or ClusterMesh participation between the current Workload Clusters.

Therefore:

```text
datacenter connectivity
    != direct Pod/Service network routing
```

## Connectivity profile taxonomy

The allocation invariant follows exported reachability, not a vague `connected`
label.

| Profile | Network contract | Pod CIDR uniqueness | Service CIDR uniqueness | Required authority |
|---|---|---|---|---|
| `isolated` | Pod/Service networks are not routed or exported across Cluster boundaries; cross-Cluster access uses explicit gateways/LB/Ingress endpoints | Not required across distinct isolation domains | Not required across distinct isolation domains | No global CIDR allocator; bounded validation is sufficient |
| `routed` | Pod routes are exported/imported inside a named routing domain | Required for every exported Pod prefix in that routing domain | Required only if Service prefixes are also exported/routed | Transactional reservation or authoritative IPAM for every prefix whose overlap is forbidden |
| `mesh-connected` | A selected mesh mechanism provides direct cross-Cluster data paths inside a named mesh domain | Determined by the selected mesh contract; any simultaneously routable/exported prefix must not overlap | Determined explicitly by the mesh Service-addressing model; never inferred | Selected mesh/IPAM authority must prove the declared non-overlap and identity rules |

`mesh-connected` intentionally does not embed product-specific assumptions. The later
forcing consumer must state which addresses become mutually reachable and which
authority owns them.

## First execution-fixture decision

The first ADR-030 disposable profile is:

```text
connectivityProfile: datacenter-isolated-v1
```

Its semantic guarantees are:

1. Pod and Service CIDRs are private to the disposable Cluster's isolation domain.
2. No Pod or Service prefix is advertised, imported, or used for direct routing to
   another Cluster.
3. Cross-Cluster/platform access uses explicitly declared LoadBalancer, ingress, or
   gateway endpoints.
4. CIDR reuse in a different isolation domain is policy-valid and is not evidence of
   collision.
5. Within the Cluster, Pod and Service CIDRs must be valid, canonical, disjoint, and
   compatible with the selected Kubernetes/CNI profile.
6. The fixture must declare any provider/node/underlay ranges that the selected CNI
   requires it not to overlap. Hidden local network knowledge cannot count as proof.
7. Changing the Cluster later to routed or mesh-connected is a new connectivity
   transition requiring a new allocation-policy decision; it is not an in-place
   automatic CIDR rewrite.

## Fixture allocation rule

For reproducibility, the reviewed execution fixture carries explicit Pod and Service
CIDRs. `auto` may be accepted as raw authoring input only if it is resolved before
semantic canonicalization and the resolution inputs/output are retained as evidence.

For the first fixture:

```text
raw authoring input
  -> bounded selector (if auto was used)
  -> explicit normalized CIDRs
  -> canonicalization
  -> R
```

The normalized contract never hashes unresolved `auto` as though it were a desired
network value.

The bounded selector must validate:

- IPv4 CIDRs parse and are in canonical network form;
- the Pod and Service CIDRs do not overlap each other;
- prefix sizes meet the selected Kubernetes/CNI test profile;
- neither CIDR overlaps a declared forbidden provider/node range;
- explicit values are preserved exactly across re-evaluation; and
- the evidence identifies the selector version and input inventory.

Because `datacenter-isolated-v1` does not promise cross-Cluster CIDR uniqueness, the
selector must not emit an allocation UID or claim global authority it does not have.

## Endpoint boundary

Control-plane and ingress LoadBalancer addresses are a separate allocation domain.
For the preferred Talos/KubeVirt disposable path:

```text
CAPK owns the LoadBalancer Service lifecycle
MetalLB owns address allocation from the provider pool
CAPK projects the observed control-plane endpoint
OpenKubes records and correlates the result
```

The execution fixture should treat the control-plane endpoint as provider-assigned
output unless a separate fixed-endpoint test is explicitly selected. A locally
predicted endpoint is not a reservation and must not be presented as authority.

## Reservation semantics for future non-isolated profiles

If a routed or mesh forcing consumer appears, its authority must define at least:

- stable allocation-domain identity;
- prefix type/address family and overlap rule;
- atomic reservation before lifecycle submission;
- allocation UID and revision bound to stable Cluster identity, not name alone;
- concurrent-writer exclusion;
- behavior when creation fails after reservation;
- retention across management restore and temporary orphan state;
- deletion/finalizer ordering before release;
- quarantine or explicit policy for name reuse; and
- provider portability or an explicit provider-scoped contract.

Automatic replacement of a running Cluster's Pod or Service CIDR is not the default
remediation for an allocation conflict.

## R1 result

```text
First fixture connectivity profile:       datacenter-isolated-v1
Cross-Cluster Pod/Service routing:         prohibited
Cross-Cluster CIDR uniqueness:             not required
Within-Cluster CIDR validation:            required
Global CIDR allocation authority:          not required for first fixture
ok-cluster auto-selection:                 deterministic convenience, not authority
Endpoint allocation:                       existing CAPK/MetalLB authority
R1 read-only closure:                      complete for first fixture
Routed/mesh product profiles:              deferred until forcing consumer
RequiresReconciler:                        none proven
Infrastructure:                            NO-GO
Failure Injection:                         NO-GO
```

This closes the CIDR blocker for the first disposable execution fixture without
claiming that every future OpenKubes connectivity profile can avoid transactional
IPAM.

## Re-evaluation triggers

Re-open the CIDR authority question when:

- a workload requires direct Pod-to-Pod routing across Clusters;
- Pod routes are exported into a shared underlay or VPN;
- a ClusterMesh/mesh profile is selected;
- Service CIDRs become routable outside their Cluster;
- concurrent provisioning across independent checkouts/regions must allocate from one
  non-overlap domain; or
- a provider requires authoritative prefix claims as lifecycle inputs.
