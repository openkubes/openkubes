# OK-141 Disposable Cluster Observation Plan

**Status:** Planned — read-only test design
**Mutation gate:** `NO-GO`
**Decision under test:** ADR-Platform-030 (`Proposed`)

Related evidence:

- [Authority and revision evidence matrix](revision-correlation.md#authority-and-revision-evidence-matrix)
- [Carrier feasibility assessment](carrier-feasibility-assessment.md)
- [Outage preflight](preflight-go-no-go.md)
- [Management-plane outage scenario](scenarios/management-plane-outage.md)

## Purpose and boundary

This plan turns every row of the authority/revision matrix into an observation with an
explicit sensor, failure domain, retained artifact, assertion, negative control, and
acceptance rule. It is not permission to create a cluster or inject a failure.

Commands in this document are observations only. A sensor that requires a missing
authority or status source is marked `BLOCKED`; the plan must not replace it with a
name match, timestamp, local file, or other weaker inference. Creation, patching,
annotation, deletion, controller pausing, and fault injection remain prohibited until
the separate preflight records a complete scope-bound `GO`.

## Test identity and required inputs

The observation runner must receive explicit values. It must not infer a production
target from the current kubeconfig context.

```text
TEST_ID
CLUSTER_NAME
CLUSTER_NAMESPACE
PROVIDER_NAMESPACE
MGMT_KUBECONFIG
INFRA_KUBECONFIG
WORKLOAD_KUBECONFIG
INTENT_FILE
CONTRACT_SCHEMA
C14N_BIN
EVIDENCE_DIR
CAPI_SYSTEM_NAMESPACE
CAPK_SYSTEM_NAMESPACE
CONTROL_PLANE_GVR
ENABLEMENT_NAMESPACE
GITOPS_KUBECONFIG
```

Preconditions for running any sensor:

1. all kubeconfig paths are readable and their cluster identities have been recorded;
2. `EVIDENCE_DIR` is outside ok-mgmt, ok-infra, and the disposable workload cluster;
3. every command and binary identity is recorded before execution;
4. output collection excludes Secret values, kubeconfig contents, tokens, private
   keys, bearer credentials, and environment dumps; and
5. synchronized UTC time and maximum observer clock skew are recorded.

## Evidence bundle contract

Every sensor writes stdout and stderr to separate files and records:

```yaml
testID: <TEST_ID>
sensorID: <O1..O10>
observer: <identity>
failureDomain: <contract|policy|mgmt|infra|workload|gitops|external-evidence>
startedAt: <RFC3339 UTC>
completedAt: <RFC3339 UTC>
command: <reviewed argv, with credential paths redacted>
exitCode: <integer>
artifact:
  path: <relative path>
  sha256: <lowercase hex>
fieldsRetained: []
assertion: <PASS|FAIL|BLOCKED>
reason: <machine-readable reason>
reviewer: <identity or PENDING>
```

`BLOCKED` is a valid read-only finding but cannot satisfy the disposable-cluster
observation gate. A command that exits successfully without producing the required
fields is `FAIL`, not `PASS`.

## Canonicalization profile for intent revision R

`R` is not the digest of YAML bytes. The test profile
`openkubes-contract-c14n/v1` performs this pipeline:

```text
raw contract
  -> parse one YAML/JSON document with duplicate keys rejected
  -> validate against the declared test-schema digest
  -> resolve scalar types through that schema
  -> apply only defaults versioned by that schema
  -> project the schema-declared semantic fields
  -> remove schema-declared non-semantic metadata
  -> encode canonical JSON using RFC 8785/JCS
  -> SHA-256 over the canonical UTF-8 bytes
```

The semantic projection includes contract type, namespace/name identity, and desired
specification. It excludes `status` and server-generated metadata such as UID,
resource version, generation, timestamps, and managed fields. Labels, annotations, and
extension fields are included only when the test schema explicitly declares them
semantic. Unknown fields fail validation; they are never silently discarded.

O1 stores all of:

```text
rawArtifactDigest
normalizedContractDigest
canonicalizationProfile: openkubes-contract-c14n/v1
testSchemaDigest
normalizedArtifactDigest
```

The canonicalizer is a checksum-pinned test-harness sensor, not a lifecycle writer.
Its required interface is:

```bash
"$C14N_BIN" canonicalize \
  --profile openkubes-contract-c14n/v1 \
  --schema "$CONTRACT_SCHEMA" \
  --input "$INTENT_FILE" \
  --normalized-output "$EVIDENCE_DIR/O1/contract.canonical.json" \
  --manifest-output "$EVIDENCE_DIR/O1/canonicalization.json"
```

Until the schema, canonicalizer implementation, binary digest, and negative-control
fixtures are reviewed, O1 is `BLOCKED/MissingCanonicalizer`; no ad-hoc `yq`, YAML
reformat, or map-key sort may substitute for it.

Required O1 negative controls:

| Fixture change | Raw digest | Normalized digest | Expected result |
|---|---:|---:|---|
| comments, whitespace, or mapping order only | different allowed | unchanged | PASS |
| omitted default versus the explicit versioned default | different allowed | unchanged | PASS |
| server metadata or non-semantic metadata only | different allowed | unchanged | PASS |
| one semantic desired field changed | different | different | PASS |
| duplicate or unknown field | any | none | validation rejected |

## Observation coverage

| Matrix claim | Sensor |
|---|---|
| Originating intent | O1 |
| Authorization and operation | O2 |
| Allocation authority | O3 |
| Owning management plane | O4 |
| Current lifecycle writer | O4 |
| Intent-to-CAPI projection | O5 |
| Object-local reconciliation | O5 |
| Machine-to-VM identity | O6 |
| Machine-to-Node identity | O6 |
| Intended enablement revision | O7 |
| `NetworkReady` outcome | O8 |
| Intended platform revision | O9 |
| `PlatformReady` outcome | O9 |
| Aggregate lifecycle result | O10 |
| Evidence persistence | O10 |

## O1 — Originating intent revision

**Claim:** one accepted semantic revision `R` is independently reproducible.

**Sensor/query:** run the versioned canonicalizer interface above, then calculate the
raw file, normalized artifact, schema, and canonicalizer-binary SHA-256 digests.

**Failure domain:** contract source plus independent evidence host.

**Raw artifacts:** original intent bytes, canonical JSON, canonicalization manifest,
schema, canonicalizer binary digest, and negative-control results.

**Fields retained:** contract identity, canonicalization profile, test-schema digest,
raw digest, normalized digest `R`, and tool digest.

**Candidate carrier:** Git commit plus `R`, or contract UID/generation plus `R`.

**Positive assertion:** every independent run over semantically equivalent fixtures
produces the same `R`; a semantic change produces another `R`.

**Negative control:** all five canonicalization controls above.

**Acceptance:** O1 passes only when the reviewed canonicalizer and every negative
control pass. **Reviewer:** contract/schema reviewer.

## O2 — Authorization and operation correlation

**Claim:** the transition to `R` was authorized for the recorded actor and target.

**Sensor/query:** query the selected policy/audit source by the immutable correlation
ID and export the complete decision record without credentials.

**Failure domain:** policy/audit system, separate from Executor-local state.

**Raw artifact:** native admission, policy, or audit record.

**Fields retained:** actor, groups/roles, operation, target identity, prior revision,
`R`, policy revision, decision, correlation ID, and decision time.

**Candidate carrier:** admission/audit record or durable operation evidence.

**Positive assertion:** exactly one allowed decision binds the actor and transition to
`R` before persistence.

**Negative control:** query an unauthorized actor and an altered target/revision; both
must be denied or absent from accepted transition evidence.

**Acceptance:** the authoritative policy source and exact read-only query must be
declared before execution. Until then O2 is `BLOCKED/MissingPolicyEvidenceQuery`.
**Reviewer:** security/policy reviewer.

## O3 — Allocation authority

**Claim:** endpoint and CIDR values originate from one current allocation record.

**Sensor/query:** export the selected allocation object by UID/revision, then export
the contract and projected Cluster/infra objects that reference it.

**Failure domain:** declared allocation authority and ok-mgmt.

**Raw artifacts:** allocation record and referencing object projections.

**Fields retained:** allocation UID, allocation revision, owner, target cluster UID,
endpoint, Pod CIDR, Service CIDR, state, and references.

**Candidate carrier:** existing IPAM/allocation CR or other reviewed allocation record.

**Positive assertion:** one current allocation record owns every observed value and is
referenced by the accepted intent/CAPI projection.

**Negative control:** equal values without the allocation UID/revision and a stale or
foreign allocation must fail correlation.

**Acceptance:** value equality never passes. No allocation authority was observed in
the current snapshot, so O3 is `BLOCKED/MissingAllocationAuthority` until one existing
mechanism is selected and its exact query recorded. **Reviewer:** network/IPAM owner.

## O4 — Management authority and active writer set

**Claim:** the expected management plane owns the lifecycle graph and no competing
management authority is active.

**Sensors/queries:** retain the top-level Cluster and controller/lease inventories:

```bash
kubectl --kubeconfig "$MGMT_KUBECONFIG" -n "$CLUSTER_NAMESPACE" \
  get cluster.cluster.x-k8s.io "$CLUSTER_NAME" -o yaml
kubectl --kubeconfig "$MGMT_KUBECONFIG" -n "$CAPI_SYSTEM_NAMESPACE" \
  get deployment,lease -o yaml
kubectl --kubeconfig "$MGMT_KUBECONFIG" -n "$CAPK_SYSTEM_NAMESPACE" \
  get deployment,lease -o yaml
```

**Failure domains:** ok-mgmt plus independent ADR-031 authority inventory.

**Raw artifacts:** Cluster object, controller Deployments, leader-election Leases,
scoped authority inventory, and fencing record if another management plane exists.

**Fields retained:** management-plane ID, authority epoch/reference, Cluster UID,
controller images, service accounts, lease holders/times, credential scope identifiers,
and fencing result.

**Candidate carrier:** Cluster metadata plus independent management/DR authority record.

**Positive assertion:** all declared lifecycle writers belong to one expected authority
and the Cluster graph names that authority.

**Negative control:** a second authority with usable credentials, or only an
unreachable previous API, must fail exclusivity.

**Acceptance:** leader election proves only intra-plane leadership. O4 remains
`BLOCKED/MissingIndependentAuthorityProof` until the independent authority sensor is
defined. **Reviewer:** Tier-0 management/DR owner.

## O5 — Intent-to-CAPI projection and object-local reconciliation

**Claim:** current CAPI/provider desired specifications trace to `R`, and each owning
controller has observed its own current object generation.

**Sensors/queries:** export the top-level object and every referenced lifecycle object:

```bash
kubectl --kubeconfig "$MGMT_KUBECONFIG" -n "$CLUSTER_NAMESPACE" \
  get cluster.cluster.x-k8s.io "$CLUSTER_NAME" -o yaml
kubectl --kubeconfig "$MGMT_KUBECONFIG" -n "$CLUSTER_NAMESPACE" \
  get machine.cluster.x-k8s.io,machinedeployment.cluster.x-k8s.io,machinehealthcheck.cluster.x-k8s.io -o yaml
kubectl --kubeconfig "$MGMT_KUBECONFIG" -n "$CLUSTER_NAMESPACE" \
  get "$CONTROL_PLANE_GVR" -o yaml
kubectl --kubeconfig "$MGMT_KUBECONFIG" -n "$CLUSTER_NAMESPACE" \
  get kubevirtcluster.infrastructure.cluster.x-k8s.io,kubevirtmachine.infrastructure.cluster.x-k8s.io -o yaml
```

**Failure domain:** ok-mgmt CAPI/CAPK APIs.

**Raw artifact:** unredacted non-Secret YAML for the complete object graph.

**Fields retained:** apiVersion/kind, namespace/name/UID, owner references, spec,
revision/digest metadata, generation, observedGeneration, Conditions, infrastructure
reference, control-plane reference, bootstrap/config references, and deletion fields.

**Candidate carrier:** revision/digest metadata on the Cluster/topology root plus a
deterministic projection record.

**Positive assertion:** the top-level UID/spec is explicitly linked to `R`; every
required descendant desired spec is attributable to that projection; every current
Condition belongs to its object's current generation.

**Negative control:** remove or alter the projected `R` in a fixture, reuse the same
names with another UID, and present a stale `observedGeneration`; all must fail.

**Acceptance:** equal object generations across resources are ignored. The exact
projection carrier/record must pass the feasibility gate before O5 can pass.
**Reviewer:** CAPI/CAPK lifecycle owner.

## O6 — Machine, provider, VM, and Node identity

**Claim:** every current Machine maps to exactly one provider VM/VMI and workload Node.

**Sensors/queries:** retain the three inventories independently:

```bash
kubectl --kubeconfig "$MGMT_KUBECONFIG" -n "$CLUSTER_NAMESPACE" \
  get machine.cluster.x-k8s.io,kubevirtmachine.infrastructure.cluster.x-k8s.io -o yaml
kubectl --kubeconfig "$INFRA_KUBECONFIG" -n "$PROVIDER_NAMESPACE" \
  get virtualmachine.kubevirt.io,virtualmachineinstance.kubevirt.io -o yaml
kubectl --kubeconfig "$WORKLOAD_KUBECONFIG" get node -o yaml
```

**Failure domains:** ok-mgmt, ok-infra, and workload cluster.

**Raw artifacts:** three independent object inventories.

**Fields retained:** UIDs, owner references, provider resource references, CAPK/CAPI
labels, VM/VMI identity, `Machine.status.nodeRef`, Node UID, and provider IDs.

**Candidate carrier:** existing CAPI/CAPK owner/reference and providerID relationships.

**Positive assertion:** each expected Machine has one current infra object, VM/VMI, and
Node with a consistent UID/reference/providerID chain.

**Negative control:** duplicate VM, reused Node name with another UID, missing nodeRef,
and mismatched providerID each fail.

**Acceptance:** names and role counts are supporting evidence only. Every identity edge
must be explicit or structurally authoritative. **Reviewer:** CAPI/CAPK and workload
observer pair.

## O7 — Intended enablement revision E

**Claim:** one durable desired enablement revision `E` is linked to `R` and owns the
observed CNI resources.

**Sensor/query:** export the selected Enablement root and its revision/profile fields,
then export the controller-owned references to Cilium resources. The exact GVR/query
is deliberately not invented here because no durable Enablement root was observed.

**Failure domains:** declared Enablement owner and workload cluster.

**Raw artifacts:** profile/root desired state, controller status, projected resource
identity, chart/image/config digests, and ownership references.

**Fields retained:** root UID/generation, profile digest, `E`, linked `R`, desired CNI
version/config digest, observed revision, Conditions, and owned-resource references.

**Candidate carrier:** existing add-on/Helm/GitOps/CAPI mechanism if it provides durable
desired state and continuous reconciliation semantics.

**Positive assertion:** `E` is explicit, durable, linked to `R`, and resolves to the
currently observed Cilium resource identity.

**Negative control:** a Helm release history entry without a desired root, or healthy
resources with another config/image digest, must fail.

**Acceptance:** O7 is `BLOCKED/MissingEnablementRoot` until the feasibility assessment
finds an existing authoritative mechanism and records its exact query. **Reviewer:**
Enablement/CNI owner.

## O8 — NetworkReady outcome

**Claim:** all profile-required network invariants are current for `E`.

**Sensors/queries:** once O7 identifies `E`, retain current Cilium and Node status:

```bash
kubectl --kubeconfig "$WORKLOAD_KUBECONFIG" -n "$ENABLEMENT_NAMESPACE" \
  get daemonset/cilium deployment/cilium-operator -o yaml
kubectl --kubeconfig "$WORKLOAD_KUBECONFIG" -n "$ENABLEMENT_NAMESPACE" \
  get configmap/cilium-config -o yaml
kubectl --kubeconfig "$WORKLOAD_KUBECONFIG" get node -o yaml
```

The selected profile must also name a pre-existing functional network probe whose
status can be queried without creating a Pod during this read-only phase.

**Failure domain:** workload cluster, observed independently of ok-mgmt.

**Raw artifacts:** Cilium DaemonSet/operator/config, Node Conditions, workload image
identities, and functional-probe result.

**Fields retained:** desired/available/updated counts, observedGeneration, Conditions,
Node `NetworkUnavailable`, image digests, config digest, probe identity/result/time,
and linkage to `E`.

**Candidate carrier:** Enablement Conditions owned by the selected mechanism.

**Positive assertion:** desired `E` is present, all required agents are updated and
available, Node networking is established, required control components are available,
and the functional probe passes.

**Negative control:** 4/4 agents with wrong `E`, unavailable operator, stale rollout,
one `NetworkUnavailable=True`, or failed functional probe each fail.

**Acceptance:** DaemonSet availability alone never passes. O8 is blocked whenever O7
cannot prove desired `E`. **Reviewer:** Enablement/CNI owner plus workload observer.

## O9 — Intended and applied platform revision P

**Claim:** the selected GitOps root applied and reports healthy the exact platform
revision `P` linked to `R`.

**Sensor/query:** for an Argo CD forcing profile, export the authoritative Applications:

```bash
kubectl --kubeconfig "$GITOPS_KUBECONFIG" \
  get application.argoproj.io -A -o yaml
```

**Failure domain:** selected GitOps control plane.

**Raw artifact:** GitOps root/Application desired and status objects plus profile
contract-check results.

**Fields retained:** Application UID/generation, requested targetRevision, applied
sync revision, sync status, health status, Conditions, linked `R`, profile identity,
and contract-check result/time.

**Candidate carrier:** authoritative GitOps root with desired and applied revisions.

**Positive assertion:** `P` is explicit, linked to `R`, reported as applied, healthy,
and passes every profile-required platform check.

**Negative control:** requested-but-not-applied revision, healthy status for another
revision, drift/out-of-sync, or failed profile check each fail.

**Acceptance:** `targetRevision` alone never passes. No GitOps Application API was
observed in the current environment, so O9 is `BLOCKED/MissingPlatformRoot` until the
forcing profile and exact root are declared. **Reviewer:** GitOps/platform owner.

## O10 — Aggregate lifecycle outcome and durable evidence

**Claim:** `Ready=True` is derived only from current, explicitly correlated source
evidence for `R`, and the proof survives Executor and cluster loss.

**Sensor/query:** a read-only evaluator consumes only the retained O1–O9 manifests and
raw artifact hashes. It must not query hidden state or write status. Its result includes
the exact input manifest hashes and required-condition profile.

**Failure domain:** independent evidence store/evaluator.

**Raw artifacts:** immutable O1–O9 manifests, evaluator input manifest, result, tool
digest, and final evidence-bundle checksum.

**Fields retained:** `R`, allocation identity, management authority, CAPI identities,
`E`, `P`, source Conditions/generations, Reasons, observation times, evaluator version,
required-condition profile, outcome, and all content hashes.

**Candidate carrier:** external evidence bundle; a normalized aggregate status may be
tested separately but is not required to evaluate the spike.

**Positive assertion:** all profile-required source claims pass for the same `R`; the
same evaluator and bundle reproduce the result after the Executor terminates.

**Negative control:** stale generation, mismatched `R`/`E`/`P`, missing artifact,
changed artifact hash, Executor-only checkpoint, or successful Executor exit without
source evidence each fail.

**Acceptance:** bundle verification succeeds from the independent evidence location
after Executor termination and, later, after disposable-cluster deletion. **Reviewer:**
independent evidence reviewer.

## Read-only checkpoint verdict

Before disposable creation can even be considered for the mutation preflight:

- O1–O10 must each have an exact reviewed sensor/query or an explicit `BLOCKED` result;
- every negative control must have a fixture or reviewed execution method;
- all observers and failure domains must be named;
- the carrier feasibility assessment must be reviewed; and
- no claim may pass by inference from names, values, timestamps, or process exit.

At this checkpoint O2, O3, O4, O7, and O9 remain explicitly blocked by missing
authoritative sources or queries. O1 is blocked until the canonicalization harness and
test schema exist. This is useful evidence about the current design; it is not evidence
that a new Reconciler is required.

**Current observation-plan result:** `INCOMPLETE / READ-ONLY`

**Infrastructure mutation decision:** `NO-GO`
