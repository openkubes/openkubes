# OK-141 Carrier Feasibility Assessment

**Status:** Read-only assessment — no carrier or component selected
**Source:** [Authority and revision evidence matrix](revision-correlation.md#authority-and-revision-evidence-matrix)
**Observation plan:** [disposable-cluster-observation-plan.md](disposable-cluster-observation-plan.md)
**Mutation gate:** `NO-GO`

## Question

Can existing mechanisms carry and expose the proof required by OK-141, without adding
durable OpenKubes-owned reconciliation?

This assessment concerns proof transport and observation. A carrier being feasible
does not prove correct projection, ownership, authorization, or readiness.

```text
carrier present
  != assertion proven

missing carrier
  != Reconciler required
```

## Classification

| Class | Meaning |
|---|---|
| **Available** | The selected stack already exposes the required identity/status relationship through an authoritative or structurally authoritative field; the disposable test still has to prove it |
| **Configurable** | An existing selected mechanism can carry the proof after explicit configuration or deterministic projection, without evidence of a new durable OpenKubes writer |
| **Missing** | No suitable current carrier or authoritative source was observed; more read-only evaluation or a bounded non-reconciling mechanism may still solve it |
| **RequiresReconciler** | Existing mechanisms have been tested and cannot maintain a required invariant; durable OpenKubes-owned reconciliation is demonstrated as necessary |

`RequiresReconciler` needs positive evidence that observation, deterministic projection,
policy, GitOps, CAPI/add-on mechanisms, and bounded evidence tooling cannot maintain the
invariant. Architectural convenience does not qualify.

## Feasibility table

| Required proof | Candidate existing mechanism | Class | Current evidence and limitation | Next read-only test |
|---|---|---|---|---|
| Raw intent identity | Git commit plus raw artifact SHA-256 | **Available** | Git/file identity can preserve exact bytes, but byte identity is not semantic revision `R` | Retain Git commit, path, raw bytes, and digest in O1 |
| Semantic intent revision `R` | Versioned test schema plus deterministic canonicalization harness | **Missing** | The normalization contract is now defined, but no reviewed schema, canonicalizer binary, or negative-control suite exists | Implement/evaluate only the read-only `openkubes-contract-c14n/v1` sensor contract and fixtures |
| Carry `R` on CAPI root | Annotation/label or topology variable on the CAPI Cluster/topology root | **Configurable** | Kubernetes metadata and topology variables can carry a value; presence alone does not prove correct projection | Test immutable `R` transport on a fixture and verify it cannot be confused with object-local generation |
| Prove intent-to-CAPI projection | Deterministic render/projection manifest containing input `R`, output spec digests, and object identities | **Configurable** | A durable evidence record can bind input and output without owning lifecycle reconciliation; no such record exists today | Compare independently normalized intended specs with retained CAPI specs and negative fixtures |
| Allocation UID/revision | Existing IPAM/allocation CR referenced by intent and CAPI objects | **Missing** | The current snapshot exposes endpoint/CIDR values but no allocation authority or UID | Inventory installed IPAM/allocation APIs and ownership before considering a new authority |
| Management-plane identity | Stable external management-plane ID and authority epoch referenced from the CAPI root | **Missing** | An annotation is technically possible but a self-asserted value is not independent authority evidence | Inventory existing DR/cluster identity records and determine which failure domain owns them |
| Intra-plane active writer | CAPI/CAPK Deployments, service accounts, scoped credentials, and leader-election Leases | **Available** | These can identify active components and leaders inside one management plane; they cannot exclude another plane | Record exact controller/lease/credential-scope fields and test duplicate leaders inside the same election domain |
| Global lifecycle-writer exclusivity | Independent authority inventory plus fencing evidence | **Missing** | No independent authority epoch/fencing source was observed; previous API unreachability is insufficient | Evaluate ADR-031 recovery inventory and fencing mechanisms without promoting a shadow plane |
| CAPI object ownership | OwnerReferences, typed refs, UIDs, spec, generation, Conditions, observedGeneration | **Available** | CAPI provides object-local ownership and reconciliation evidence; generations remain local to each object | Capture the complete disposable object graph and inject stale/foreign fixtures into the read-only evaluator |
| Machine to KubeVirt VM/VMI | InfraMachine references, CAPK labels, owner relationships, and provider identity | **Available** | CAPK/KubeVirt expose structural relationships; the current `ok-ai` snapshot lacks the originating Machines | Prove exact UID/reference cardinality while disposable CAPI objects remain present |
| Machine to workload Node | `Machine.status.nodeRef`, Node UID, and `spec.providerID` | **Available** | CAPI and Kubernetes already expose the intended relationship when lifecycle objects exist | Verify one-to-one mapping and negative fixtures for reused names/providerID mismatch |
| Desired enablement revision `E` | Existing CAPI add-on, Helm, GitOps, or other controller-owned desired root | **Missing** | Cilium runtime identity is visible, but no durable desired Enablement root or revision linked to `R` was observed | Inventory installed add-on APIs and current Cilium ownership; evaluate upgrade/health semantics before selecting a root |
| Observed Cilium identity | DaemonSet/operator images, Helm metadata, Cilium config, and object generations | **Available** | Runtime version/config can be observed; Helm history or healthy Pods are not an authoritative desired `E` | Define the exact image/config digest projection and compare it with a future declared `E` |
| Network health signals | Cilium rollout status, operator availability, Node Conditions, and a pre-existing functional probe | **Available** | Required raw signals are readable; the profile requirement set and functional probe are not yet fixed | Define a minimal profile and prove every signal plus negative controls in O8 |
| Authoritative `NetworkReady` Condition | Condition owned by the selected Enablement mechanism | **Missing** | No current durable Enablement owner publishes revision-aware readiness | First test whether an existing add-on/GitOps mechanism can publish or expose sufficient source Conditions |
| Desired/applied platform revision `P` | GitOps root with requested and applied revision, such as an Argo CD Application | **Missing** | No Argo Application API/root was observed on current management or workload clusters | Select a forcing GitOps profile and confirm its native desired/applied/health fields before adding OpenKubes status |
| Platform health source | GitOps health/sync plus profile-owned contract checks | **Configurable** | Standard GitOps status can expose sync/health once a root exists; required OpenKubes profile checks remain undefined | Map one proposed forcing profile to native GitOps status and read-only checks |
| Aggregate result | Read-only evaluator over source manifests and hashes | **Configurable** | ADR-030 allows evidence evaluation without preselecting a status-writing controller | Build a deterministic evaluator fixture and prove stale/mismatched/missing inputs fail closed |
| Durable evidence | External content-addressed evidence bundle | **Missing** | Current snapshots can be retained manually but are not linked to authorization, `R`, `E`, `P`, and outcome as one bundle | Evaluate existing artifact/audit storage and retention before proposing a new service |

## Carrier-specific conclusions

### R — OpenKubes semantic intent revision

Git can retain the raw artifact, and CAPI metadata can transport an already computed
`R`. Neither computes or validates semantic identity. Feasibility therefore splits:

```text
raw artifact identity   Available
R canonicalization      Missing
R transport             Configurable
R projection proof      Configurable
```

The missing canonicalization sensor is read-only test tooling. It is not evidence for
a lifecycle Reconciler.

### E — Enablement revision

Cilium runtime identity and health signals are Available. A durable desired root that
owns `E`, links it to `R`, and exposes revision-aware health is Missing. Existing CAPI
add-on, Helm-controller, or GitOps mechanisms must be inventoried for continuous apply,
upgrade, ownership, and Condition semantics before this gap can be classified further.

### P — Platform revision

A GitOps Application-like object can normally carry requested and applied revisions,
but no such authoritative platform root was observed in the current environment.
`P` remains Missing for the forcing profile rather than assumed from Git history.

### Allocation UID

No allocation authority was observed. CAPI or Kubernetes objects can carry an
allocation reference only after an authority has issued one. A label containing an IP
or invented UUID would transport data without proving allocation ownership.

### Management authority identity

CAPI metadata can transport a management-plane ID, and leader-election Leases can show
intra-plane leadership. Neither independently proves global writer exclusivity. The
authority identity and fencing proof must come from a separate ADR-031 failure domain.

## RequiresReconciler assessment

No row currently meets the `RequiresReconciler` evidence threshold.

The current distribution is:

```text
Available           runtime/object relationships and health sensors
Configurable        R transport/projection, platform health, aggregate evaluation
Missing             canonicalization, allocation authority, global writer proof,
                    desired E, authoritative NetworkReady, desired/applied P,
                    durable evidence bundle
RequiresReconciler  none proven
```

Missing items may eventually require durable OpenKubes reconciliation, but that can be
claimed only after the relevant existing mechanism has been configured or tested and
has failed the required invariant. Until then the Operator outcome remains
**A/B/C/D unclassified**.

## Decision gate

The read-only carrier assessment is complete enough to design sensors, not to authorize
the disposable cluster. Before mutation review:

1. every `Available` row needs an exact query and negative-control fixture;
2. every `Configurable` row needs one bounded candidate configuration and a failure
   criterion;
3. every `Missing` row needs an inventory of existing mechanisms and an explicit
   reason they do or do not satisfy the invariant; and
4. any future `RequiresReconciler` classification needs reviewed evidence that the
   existing mechanisms cannot own the invariant safely.

**Operator required:** not proven

**Public API required:** not proven

**Infrastructure mutation:** `NO-GO`
