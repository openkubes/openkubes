# Allocation Authority Mechanism Evaluation

**Ticket:** OK-141

**Baseline:** `main` at `0ef9995`

**Input:** [allocation-authority-observation.md](allocation-authority-observation.md)

**Evaluation date:** 2026-08-09

**Infrastructure mutation:** `NO-GO`

## Question

Does the allocation gap require a new OpenKubes-owned control loop, or can its
invariants be owned by an existing allocator, provider, deterministic function,
or bounded policy?

## Result

```text
Control-plane endpoint runtime allocation   Existing mechanism sufficient
Fixed endpoint request/provenance            Existing mechanism configurable
Pod/Service CIDR allocation                  Still unresolved

Overall Allocation Authority gap             Still unresolved
RequiresReconciler                           none proven
A/B/C/D                                      unclassified
```

The overall result stays unresolved because a single label would otherwise hide
the difference between the already authoritative endpoint path and the undefined
CIDR invariant.

## Mechanism assessment

### Local `ok-cluster` selector

**Capability:** calculates a first-free endpoint, Pod CIDR, and Service CIDR and
materializes them into rendered configuration.

**Assessment:** useful deterministic function, not an authority.

It has no atomic reservation, durable owner identity, allocation UID, concurrent
writer exclusion, or authoritative release operation. API-unreachable endpoint
fallback and local-only CIDR discovery further prevent it from proving global
uniqueness. It should not be promoted to authority merely by wrapping it in a CLI
or runner.

### CAPK plus MetalLB for KubeVirt endpoints

**Capability:** CAPK owns the control-plane LoadBalancer Service lifecycle;
MetalLB transactionally selects or validates an address from its pool; CAPK
projects the observed endpoint into KubevirtCluster and CAPI Cluster state.

**Assessment:** existing mechanism sufficient for runtime allocation.

The natural writers are already CAPK and MetalLB. A new OpenKubes reconciler for
the same endpoint would duplicate ownership. OpenKubes may still need a
deterministic evaluator to correlate:

```text
Service UID + pool + assigned address
  <-> KubevirtCluster UID/endpoint
  <-> CAPI Cluster UID/endpoint
  <-> requested contract revision R
```

Correlation and evidence do not require corrective OpenKubes reconciliation.

For contracts that require a fixed endpoint, the existing CAPK Service template
can carry a MetalLB address request. MetalLB documents that an address already in
use cannot be assigned and surfaces the failure on the Service. This is
`Configurable`, not proof that the present local preselection is race-free.

The preferred Talos/KubeVirt hypothesis for a later disposable test is to treat
the CAPK/MetalLB result as output of the authoritative provider path rather than
pretending that the renderer reserved it. No mutation was performed to validate
this hypothesis.

### Generic CAPI IPAM contract

Cluster API defines `IPAddressClaim`/`IPAddress` as a provider contract. An IPAM
provider watches claims referencing its pools, allocates an address, creates the
durable IPAddress object, and deallocates it on claim deletion. Infrastructure
providers must explicitly support creation and consumption of those claims.

**Assessment:** available contract surface, but no installed authority observed.

The CRDs alone are not an allocator. No provider-specific pool CRDs, provider
controller, claims, or addresses were present in the live inventory.

The upstream in-cluster IPAM provider is a plausible existing provider for
individual addresses. Its current prefix-pool feature allocates IPv6 prefixes;
it does not directly establish an IPv4 `/16` Pod-CIDR and `/20` Service-CIDR
allocation path for this OpenKubes profile. Selecting it would also require proof
that the consuming infrastructure or composition supports the intended claim.

References:

- [Cluster API IPAM provider contract](https://main.cluster-api.sigs.k8s.io/developer/providers/contracts/ipam)
- [Cluster API in-cluster IPAM provider](https://github.com/kubernetes-sigs/cluster-api-ipam-provider-in-cluster)

### Cilium and Kubernetes in-cluster pools

Observed Cilium pool APIs and Kubernetes ServiceCIDR/IPAddress APIs govern
addresses inside one Kubernetes cluster. They are not evidence of an authority
that assigns non-overlapping Pod-/Service-CIDR blocks to multiple workload
clusters.

**Assessment:** wrong ownership scope for the unresolved inter-cluster question.

### Crossplane OpenKubes claim/composition

The current OpenKubes Crossplane cluster claim requires `endpointIP` and passes it
through to rendered CAPI resources. It does not allocate or reserve the value.

**Assessment:** current carrier only, not allocation authority.

Crossplane could host a future claim-based composition, but doing so would first
require an explicit invariant and a transactional backing authority. The mere
existence of a Crossplane reconciler does not make a template-generated value an
allocation proof.

## Reconciler necessity test

### Endpoint address

1. **OpenKubes-specific desired state:** no; the endpoint belongs to provider and
   LoadBalancer Service lifecycle state.
2. **Can it drift after submission:** yes, through Service/pool lifecycle changes.
3. **Does drift matter:** yes, the API endpoint must remain reachable and
   correlated.
4. **Continuous detection required:** yes.
5. **Repeated correction required:** yes.
6. **Existing authoritative controller:** yes, CAPK plus MetalLB.
7. **Deterministic evaluator sufficient for OpenKubes:** yes, for correlation and
   evidence; correction remains with existing owners.
8. **Duplicate ownership risk:** high if an OpenKubes controller also writes the
   Service allocation or CAPI endpoint.

**RequiresReconciler:** `No` for a new OpenKubes-owned endpoint loop.

### Pod and Service CIDRs

1. **OpenKubes-specific desired state:** unresolved; OpenKubes carries the values,
   but required uniqueness scope is not defined.
2. **Can it drift after submission:** the CAPI values are normally stable, while
   external topology/connectivity can change whether overlap is acceptable.
3. **Does drift matter:** only when the selected connectivity/profile invariant
   forbids overlap.
4. **Continuous detection required:** unresolved; admission-time reservation may
   be sufficient if external use cannot bypass the same authority.
5. **Repeated correction required:** unsafe after cluster creation; automatic CIDR
   replacement is not an acceptable default remediation.
6. **Existing authoritative controller:** none observed for multi-cluster IPv4
   CIDR blocks.
7. **Deterministic mechanism sufficient:** possibly for bounded, reviewed,
   isolated profiles; not for concurrent globally unique allocation.
8. **Duplicate ownership risk:** high if OpenKubes competes with network/IPAM or
   provider ownership introduced later.

**RequiresReconciler:** `Unresolved`, not `Proven`.

The missing fact is the invariant, not merely a component:

```text
isolated workload clusters
  -> CIDR reuse may be policy-valid

connected / routed / mesh-participating clusters
  -> non-overlap may be required within a declared routing domain
```

Without that scope, no allocator can be evaluated correctly.

## Why this does not prove an OpenKubes operator

The only demonstrated continuous control loop is already owned by CAPK and
MetalLB. The unresolved CIDR problem may be satisfied by:

- a bounded static inventory with admission-time conflict checks;
- an existing external IPAM authority;
- a transactional reservation service;
- an IPAM provider integration;
- profile policy that explicitly permits reuse for isolated clusters.

Some options are persistent and critical, but persistence alone is not Cluster
lifecycle reconciliation. No evidence currently satisfies the full `C` threshold
from `reconciler-necessity-test.md`.

## Follow-up evidence needed

The next read-only allocation checkpoint should define and review:

1. allocation domains, such as isolated, routed, or mesh-connected;
2. uniqueness requirements per value and domain;
3. whether endpoint addresses are desired inputs or provider-assigned outputs;
4. reservation lifetime across failed creation, deletion, restore, and name reuse;
5. provider portability requirements, especially KubeVirt/MetalLB versus
   OpenStack/provider-native load balancers;
6. whether any existing organizational IPAM system can own IPv4 prefix claims.

Only after those facts exist can a disposable test choose a candidate mechanism.
Until then:

```text
Allocation Authority:  Still unresolved
RequiresReconciler:    none proven
A/B/C/D:               unclassified
Infrastructure:        NO-GO
Failure Injection:     NO-GO
```
