# ADR-Platform-050: Virtual Cluster Models and Provider-Neutral Lifecycle Boundaries

**Date:** 2026-11-22  
**Status:** Proposed — architecture only; implementation selection and production adoption pending OK-235  
**Related:** ADR-Platform-001, ADR-Platform-007, ADR-Platform-011, ADR-Platform-013, ADR-Platform-017, ADR-Platform-023, ADR-Platform-030, ADR-Platform-034 (Proposed), ADR-Platform-047 (Proposed), ADR-Platform-048 (Proposed); OK-76, OK-141, OK-232, OK-235  
**Scope:** Cluster taxonomy and adapter boundaries, not an accepted public API

## 1. Context

OpenKubes provisions and operates Kubernetes through the `ok` CLI and infrastructure/lifecycle integrations including CAPI/BYOH. Distinct requests are emerging for (1) full Kubernetes clusters on VM/bare metal, (2) full Kubernetes clusters on KubeVirt VMs, and (3) virtual Kubernetes control planes hosted inside an existing Kubernetes cluster. These must not share unqualified capability or isolation claims.

CAPI/BYOH remains independent of KubeVirt and vCluster. Cilium is the standard CNI profile for CAPI/BYOH-provisioned full clusters; KubeVirt and Longhorn are separate optional capabilities. The first vCluster spike targets an eligible HA Kubernetes host in LAB Stack B / C. The precise infrastructure provider, topology and placement are environment-specific test inputs, not part of this architectural contract. No live infrastructure changes are authorized by this ADR.

OpenKubes owns contracts rather than reimplementing platform components (ADR-001). ADR-013 separates workload-cluster registration from provisioning. ADR-030 distinguishes contract/policy/executor/controller authority; ADR-034 *proposes* semantics for `ok validate/plan/up/status/down` and requested revision transitions. Proposed ADRs must not be presented as accepted stable CLI functionality. Current CLI schema and command behavior in `openkubes/ok-cluster` must be explicitly mapped before any implementation.

## 2. Problem statement and decision drivers

How can a single OpenKubes-facing cluster workflow represent substantially different cluster models without claiming equivalent node lifecycle, isolation, networking, security or disaster recovery capabilities?

Drivers: explicit capability negotiation, stable identity, independent provider maintenance, least privilege, host dependency tracking, idempotent declarative reconciliation, audit and durable evidence, safe deletion, versioned licensing/distribution, low-commitment feasibility testing.

## 3. Definitions and non-equivalence

| Model | Proposed type vocabulary | Actual compute / ownership | Lifecycle boundary |
|---|---|---|---|
| Standard Kubernetes | `infrastructure-cluster` | Dedicated/managed VM or bare-metal control plane and workers | CAPI/BYOH or another full-cluster provider |
| Virtual Nested Cluster (VNC) | `nested-infrastructure-cluster` | Full Kubernetes on KubeVirt guest VMs within a host cluster | Guest cluster + KubeVirt VM adapter; separate spike |
| vCluster | `virtual-control-plane` | Separate logical Kubernetes API/control plane; first PoC uses shared host workers | vCluster adapter owns virtual control plane, not host worker infrastructure |

`VNC` is an OpenKubes architectural term; `vCluster` is the upstream project's product name. They are not synonyms. Some upstream editions/modes may support private nodes, so isolation/worker topology must be modeled separately from cluster type. Do not imply that `virtual-control-plane` always means shared nodes.

For shared-node vClusters, independent virtual API/RBAC does **not** establish a separate kernel, host CNI, node lifecycle, VM failure domain, host CRDs/admission boundary, storage backend, network policy enforcement, infrastructure upgrade authority, host-independent HA, or full VM/worker provisioning. Host control-plane failures, quotas and scheduler behavior remain relevant. Namespace/API isolation, data-plane network isolation, and host-security isolation require separate evidence.

## 4. Candidate architecture: common contract, different adapters

```text
ok CLI / optional other clients
          |
parse -> validate -> canonical desired state
          |
policy/authority -> bounded executor -> status/evidence
          |
provider-neutral cluster lifecycle interface
          +-- Full-cluster adapter: CAPI/BYOH
          +-- Virtual-control-plane adapter: vCluster [candidate]
          +-- Nested full-cluster adapter: KubeVirt/VNC [future]
```

Provider-independent identity is not a license to treat every target as a full cluster. The candidate schema must distinguish:

- `clusterIdentity` (stable name + immutable UID / incarnation), `clusterType`, `providerRef`, versioned implementation profile and capability declarations.
- `ownerRef`, installation actor, authority profile, tenancy/authorization domain, management registration status, provenance and creation/deletion attribution.
- `hostClusterRef` (mandatory for hosted models), host namespace, allowed platform/host identities, credentials as references, host readiness and capacity gates.
- Canonical desired revision, transition/acceptance identity, observed provider conditions, cleanup/evidence references and explicit `DESIRED_ABSENT` versus `CONFIRMED_ABSENT`.
- Capability flags or versioned operation support (e.g. `virtualAPI`, `workerNodesOwned`, `nodeUpgrade`, `hostCNIManaged`, `privateNodes`, `crdIsolation`, `networkIsolationProven`, `customResourceSync`, `independentFailureDomain`). A flag may be `unknown` until tested; never default unproven safety claims to true.

Field names above are illustrative design candidates, **not accepted** `apiVersion`, `kind`, CLI flags, defaults or backward compatibility guarantees. An adapter must reject unsupported operations rather than silently converting them to other semantics.

## 5. Options (no implementation decision yet)

### A. Direct vCluster provider/adapter within `ok`
`ok` invokes an approved, pinned upstream vCluster CLI/Helm or SDK integration behind the shared lifecycle contract. Advantages: direct UX, small integration surface, no additional reconciliation controller. Costs: need to own status projection, version compatibility, drift/convergence, retries, evidence, and safe authority isolation. CLI execution must not become an untracked second source of truth.

### B. Operator / Kubernetes CRDs
A scoped controller reconciles a declarative custom resource, invoked/observed through the same `ok` contract. Advantages: Kubernetes-native continuous reconciliation, observability and GitOps fit. Costs: controller installation/RBAC and CRD governance, upgrading/retiring CRDs, host-wide security blast radius, extra operational dependencies. An Operator does not by itself provide immutable authorization, secure evidence, or audit guarantees. The CRD must remain an implementation projection, not an alternative authoritative schema.

### C. Optional add-on only
Offer a documented pinned vCluster installation on eligible host clusters, with no first-class virtual-cluster lifecycle provider. Advantages: fastest bounded evaluation and least coupling. Costs: cannot claim complete `ok` Create/Status/Update/Delete, single lifecycle authority, or automated recovery. Status may be a clearly labeled read-only integration probe.

| Criterion | A Direct | B Operator | C Add-on |
|---|---|---|---|
| First PoC complexity | Medium | High | Low |
| Continuous reconcile / GitOps | Must build | Native fit, but policy integration required | Install-level only |
| `ok` cluster lifecycle completeness | Feasible after contract work | Feasible after controller integration | Not provided |
| RBAC and authority attack surface | CLI/executor | Host controller/CRDs | Operator/manual |
| Operational dependency | Pinned CLI/Helm | Controller + CRDs | Pinned tooling |
| Evidence and reversible cleanup | Must implement | Must implement | Manual/test harness |

**Proposed disposition:** evaluate C as a *test harness*, and compare A vs B for eventual lifecycle integration. No provider selection or promotion of C to the final architecture is accepted here. OK-235 records the Go/No-Go based on evidence. If A/B cannot uphold the shared contract, retain C as an explicit add-on only.

## 6. Lifecycle and CLI semantics

Conceptual provider operations are `Create`, `Observe/Status`, `Update`, and `Delete`; desired-state transitions and authority are governed outside the provider. If/when ADR-034 is accepted or superseded, align `ok validate`, `ok plan`, `ok up`, `ok status`, and `ok down` with the actual versioned CLI contract.

- **Create:** validate host cluster identity/readiness, namespace policy, capacity/quota, release/chart/digest, isolation prerequisites, admission and service-account permissions. Correlate provisioned host objects to a stable cluster UID.
- **Status:** read-only normalized condition with provider version, host-ref health and ownership; distinguish control-plane Ready from host/workload/network Ready. Unknown != healthy.
- **Update:** explicit supported revision diff, version/skew and chart compatibility, credential rotation and failure/retry handling. Do not claim worker Kubernetes or CNI upgrades.
- **Delete:** independently authorized destructive transition; retain desired absence until confirmed cleanup; inventory/finalizers, host namespaces, managed workloads, virtual API credentials, registrations and surviving resources. The evidence ledger must outlive removed resources. No force-deletion or finalizer bypass by default.
- **Retry/recovery:** idempotent requests keyed to immutable resource identity and transition; uncertain writes require observation before re-submit. Drift must not be mistaken for a new desired-state transition.

## 7. Authentication, RBAC, namespaces, CRDs and isolation

Use explicitly selected host and virtual kubeconfigs, never inferred current context. Store credentials in appropriate secret mechanisms, not Git, CLI output or evidence. Separate principals: host installer/executor, vCluster administrator, tenant workload user, host operator, management registrant. Restrict host API verbs and allowlist target namespaces and relevant CRDs. Virtual RBAC tests include allow/deny and attempts to access host resources.

Use distinct host namespaces and scoped `ResourceQuota`, `LimitRange`, network policies (where supported/enforced), pod admission and security profiles. Namespace segregation alone is not a multi-tenant security boundary. Verify cross-vCluster API isolation **and** actual traffic/data-plane policy independently.

Virtual API CRDs are not automatically host CRDs. Any host-CRD exposure or bidirectional custom-resource sync must be explicitly reviewed, license-checked, versioned, least-privilege scoped and tested; exclude custom-resource sync from the initial OSS spike.

## 8. GitOps, ownership, registration, audit and evidence

One canonical desired-state authority; provider CRDs, Helm releases and generated manifests are derived implementation artifacts. Git stores non-secret desired config plus stable version/digest and owner reference; runtime identity and last accepted canonical config must be recoverable without relying on a local laptop. Imperative calls must emit reconstructible, auditable intent (or be marked non-compliant for managed operation) rather than becoming a shadow authority. Preserve revision linkage and drift diagnostics.

Creation does not imply registration in the OpenKubes management plane: ADR-013 requires explicit opt-in and one platform identity/credential source. A virtual API may qualify for limited workload registration only when capabilities and policy are checked; registration is not an assertion of full-cluster equivalence. Re-provisioning demands credential replacement/re-registration; deregistration and revocation are separately authorized.

Capture actor, installation method and version, host and virtual identity, requested/accepted revisions, policy decision, submit/result, timestamps, provider observations, cleanup inventory and durable evidence digests. Remove tokens and kubeconfig material. Host-owned logs are insufficient on their own for post-deletion historical proof.

## 9. Licensing, distribution and support boundaries

Target a version-pinned, verifiable upstream OSS shared-node profile for the first spike. Before installation, independently verify exact upstream release, chart/source hashes, license, commercial/Platform connectivity requirements, security features, feature availability and air-gap support for the selected distribution. Do not assume private nodes, SSO, custom-resource sync, enterprise audit or private network isolation are available in every edition. Record a feature/edition matrix as evidence. No bundled or redistributed proprietary component without an explicit review.

## 10. LAB Stack B / C proof-of-concept plan (OK-235)

Prerequisite: an eligible HA Kubernetes host cluster in LAB Stack B / C, tested connectivity, documented topology and capacity, and approved isolated namespaces. The exact host platform and node count are supplied by the test environment; the vCluster integration contract MUST remain infrastructure-provider-neutral. CAPI/BYOH provisioning and management handover remain independent tasks. No modifications to LAB Stack B / C during this design phase.

**Execution design after a separate approval:**

1. Verify host kubeconfig and scoped permissions; record current state, workload and namespace baseline, quota/headroom and exact upstream artifacts.
2. Install vCluster A into approved host namespace; capture creation latency, initial CPU/RAM, readiness and installation identity.
3. Retrieve and validate independently scoped virtual kubeconfig without persisting plaintext secrets in the evidence bundle.
4. Exercise API/RBAC allow/deny, deploy a workload, install a test virtual CRD, inventory any host-side CRD/admission changes.
5. Install vCluster B in separate host namespace and test visibility boundaries, network isolation and resource quotas.
6. Sample idle/loaded resource use and startup behavior with recorded host and guest versions.
7. Exercise a read-only `ok status` prototype or mocked contract mapping with host dependency and honest unknown states.
8. Execute one bounded version/config update and retries; test host unavailable/quota exhausted/interrupted cleanup as feasible and approved.
9. Request controlled deletion; verify namespace/resources, virtual credentials, registration state and residual host resources; store redacted evidence externally.
10. Produce a diff between provider implementations A/B and installation-only C, with measured Go/No-Go.

**Test identifiers:** VC-01 Create, VC-02 virtual API/kubeconfig, VC-03 RBAC, VC-04 workload, VC-05 CRD, VC-06 two-vCluster isolation, VC-07 quota, VC-08 performance, VC-09 `ok` status, VC-10 update, VC-11 deletion, VC-12 fault handling. Detailed pass/fail probes, cleanup approvals and evidence schema belong to OK-235.

No benchmark, security isolation guarantee, SLA or E2E pass is asserted by this design document.

## 11. Consequences, risks and open questions

**Positive if adopted:** consistent cluster identity/UX, strict non-equivalence of capabilities, option to integrate additional models, shared authority and traceability.

**Costs/risks:** adapter compatibility with upstream changes; privileged host installer/operator; multi-tenant escape via host API, sync or network; quota interference and noisy neighbors; credential leakage; ambiguous cleanup ownership; host outages; split lifecycle authority; license and redistribution drift.

**Decision gates for OK-235:**

1. Which exact `ok-cluster` executable/schema/command semantics and ADR-030/034 implementation subset exist at the chosen base commit?
2. Who is authoritative for the desired state, and what minimal contract must A/B satisfy without bypassing policy?
3. Can host access be constrained to namespace/verb/resource allowlists and can credentials be independently rotated/revoked?
4. Which supported release/edition provides required functionality without non-OSS dependencies?
5. Is host network isolation measurable and sufficient for the target threat model? What is explicitly **not** isolated?
6. Can failure and deletion be reconciled with externally retained durable evidence?
7. What concrete acceptance results favor A or B over C? What remains unsupported?
8. Is management-plane registration of a virtual cluster warranted, and if so which capabilities may consume it?

## 12. Roadmap and decision status

- **Phase 1 — ADR + contract inventory:** this Proposed ADR, OK-235 and read-only review of repository/CLI.
- **Phase 2 — vCluster PoC:** only after LAB Stack B / C host-cluster readiness and explicit change authorization; capture VC-01…VC-12.
- **Phase 3 — `ok` integration:** separate implementation proposal after A/B/C decision, compatibility tests and security gates.
- **Phase 4 — optional VNC evaluation:** full Kubernetes on KubeVirt VMs as a separate provider track, referencing OK-141 and OK-232; no dependency forced into BYOH.

**Proposed decision:** accept the three-way taxonomy and provider-neutral capability/authority boundaries for design discussion; *defer* selecting A/B/C, schema version, and production support to OK-235. This ADR's `Proposed` status does not authorize implementation or infra changes.

## References

- [OK-235 — vCluster Integration Spike](https://kubernauts.atlassian.net/browse/OK-235)
- [OK-76 — `ok` CLI Evaluation](https://kubernauts.atlassian.net/browse/OK-76)
- [OK-141 — Disposable Cluster](https://kubernauts.atlassian.net/browse/OK-141)
- [OK-232 — Multi-Architecture KubeVirt/Talos](https://kubernauts.atlassian.net/browse/OK-232)
- [ADR-Platform-013](ADR-Platform-013-workload-cluster-registration.md)
- [ADR-Platform-030](ADR-Platform-030-control-plane-execution-model.md)
- [ADR-Platform-034](ADR-Platform-034-ok-up.md)
- [ADR-Platform-048](ADR-Platform-048-infrastructure-lifecycle-strategies.md)
