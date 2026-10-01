# ADR-Platform-039: OpenStack as an Optional OpenKubes IaaS Composition

- **Status:** Proposed — pending OK-184 acceptance evidence
- **Date:** 2026-10-01
- **Tracking:** OK-184
- **Scope:** Optional IaaS capability / composition
- **Forcing implementation:** OpenStack-Helm
- **Related:** ADR-Platform-001 (Contracts, not Components), ADR-Platform-009 (Storage Contract), ADR-Platform-010 (Ingress Contract), ADR-Platform-013 (Cluster Registration), ADR-Platform-017 (Constraint Envelopes), ADR-Platform-020 (Shared Platform Services), ADR-Platform-023 (Implementation Profiles)

---

## 1. Context

OpenKubes already treats Kubernetes clusters, platform services and vertical capabilities as consumers of stable contracts rather than as one fixed software distribution. It also supports VM-oriented infrastructure through KubeVirt in parts of the current implementation.

A different use case exists for consumers that need a conventional IaaS surface: projects/tenants, images, flavors, virtual networks, floating IPs, block volumes and VM lifecycle through an OpenStack API.

OpenStack-Helm provides a forcing implementation for testing whether such an IaaS can itself run on an OpenKubes Kubernetes substrate. This creates an important architectural question:

> Can OpenStack be an optional OpenKubes composition without OpenKubes becoming an OpenStack distribution and without OpenStack-specific semantics leaking into mandatory platform contracts?

This ADR proposes a boundary and defines the evidence required before that boundary can be accepted.

## 2. Decision drivers

- Preserve ADR-Platform-001: OpenKubes owns contracts, not components.
- Keep OpenStack optional and removable.
- Avoid prematurely declaring KubeVirt and OpenStack interchangeable.
- Support a conventional IaaS API where that is a real consumer requirement.
- Make host-coupled compute/network/storage prerequisites explicit.
- Require functional evidence rather than treating successful Helm reconciliation as service readiness.
- Keep OpenStack API and lifecycle semantics owned by OpenStack.
- Preserve failure isolation between the optional IaaS composition and unrelated OpenKubes capabilities.

## 3. Proposed decision

OpenKubes **MAY** provide an optional `ok-openstack` composition.

The composition consumes OpenKubes substrate capabilities and a declared constraint envelope. OpenStack-Helm is the first forcing implementation, but it is **not** part of the OpenKubes platform contract.

```text
Physical / virtual infrastructure
          |
          v
OpenKubes Kubernetes substrate
          |
          +-- storage / network / identity / observability capabilities
          |
          +-- declared host constraint envelope
          |     KVM, devices, kernel/runtime/network requirements
          |
          v
optional ok-openstack composition
          |
          v
OpenStack-Helm implementation
          |
          +-- Keystone
          +-- Nova
          +-- Neutron
          +-- Glance
          +-- Cinder
          +-- implementation dependencies
          |
          v
OpenStack API / IaaS semantics
```

### 3.1 Ownership boundary

OpenKubes owns only the portable prerequisites and evidence boundary that are justified by more than one implementation or by an existing OpenKubes contract.

OpenStack owns:

- Keystone identity semantics;
- Nova server/flavor semantics;
- Neutron network/router/floating-IP semantics;
- Glance image semantics;
- Cinder volume semantics;
- OpenStack service topology and internal dependencies;
- OpenStack upgrade and compatibility rules.

The `ok-openstack` composition may translate OpenKubes capabilities into OpenStack-Helm configuration. Translation does not transfer ownership of OpenStack semantics to OpenKubes.

### 3.2 OpenStack is not a foundation dependency

No core OpenKubes capability may require OpenStack merely because `ok-openstack` exists.

Removal or failure of `ok-openstack` MUST NOT invalidate unrelated OpenKubes contracts except where a consumer explicitly depends on an OpenStack-provided resource.

### 3.3 KubeVirt and OpenStack remain distinct

This ADR does **not** define a generic OpenKubes VM API.

KubeVirt expresses virtual machines as Kubernetes resources. OpenStack exposes an IaaS resource model with its own tenant, network, image, compute and block-storage semantics. Those models overlap in implementation capability but are not assumed to have equivalent contracts.

A future common compute contract requires independent forcing consumers and evidence that the abstraction preserves useful semantics rather than hiding them.

For this ADR:

```text
Kubernetes-native VM consumer --> KubeVirt API/profile

IaaS consumer                --> OpenStack API/profile
```

Neither is designated the universal VM abstraction.

## 4. Constraint envelope

An OpenStack implementation profile MUST declare every substrate assumption required for safe operation.

At minimum OK-184 must determine whether the tested profile requires:

- hardware virtualization and `/dev/kvm`;
- privileged containers or additional Linux capabilities;
- host PID/network namespaces;
- host paths or mount propagation;
- kernel modules and sysctls;
- node labels/taints and dedicated compute placement;
- Open vSwitch or alternative Neutron dataplane requirements;
- MTU/encapsulation constraints;
- external/floating-IP network attachment;
- storage classes for control-plane persistence;
- direct Ceph/RBD or other Cinder backend access;
- load-balancer/Gateway/ingress prerequisites;
- DNS, certificates and externally reachable API endpoints.

A requirement being necessary for OpenStack does not automatically make it an OpenKubes-wide requirement.

## 5. Readiness and evidence

`HelmRelease=Ready`, Pods being `Running`, or OpenStack services reporting configuration are insufficient evidence of delivered IaaS function.

The reference profile MUST prove at least:

### 5.1 Identity evidence

A client can authenticate against Keystone using the intended external API path.

### 5.2 Compute evidence

A VM can be created through the OpenStack API and reaches the expected lifecycle state on a compute host with the pinned implementation.

### 5.3 Network evidence

The VM obtains the intended tenant connectivity. If the profile claims external/floating-IP connectivity, that path must be functionally probed.

### 5.4 Storage evidence

A Cinder volume can be created, attached, written, read and detached through the supported path.

### 5.5 Failure/reconciliation evidence

At least one relevant node/service disruption is exercised and the resulting recovery boundary recorded.

### 5.6 Isolation/removal evidence

The optional composition can be removed without damaging unrelated OpenKubes capabilities.

Evidence MUST identify the tested source revisions, chart versions, image digests, Kubernetes version, host/runtime profile and relevant network/storage configuration.

## 6. Security boundary

OpenStack compute and networking may require materially more host authority than ordinary Kubernetes workloads.

Therefore `ok-openstack` MUST NOT be described as an ordinary application composition until OK-184 has enumerated its effective privileges.

The spike must record:

- privileged workloads;
- Linux capabilities;
- host namespaces;
- host mounts/devices;
- kernel/runtime mutation;
- secret distribution;
- service-account/RBAC scope;
- access to storage/network control planes;
- blast radius of a compromised compute/network pod.

If the required authority conflicts with an existing OpenKubes isolation invariant, the reference profile is rejected or constrained to dedicated nodes/clusters. The invariant is not weakened silently to make OpenStack fit.

## 7. Placement

This ADR does not yet prescribe that OpenStack run on `ok-mgmt`, a workload cluster, or a dedicated `ok-openstack` cluster.

OK-184 must decide placement from evidence, considering:

- privileged host access;
- failure blast radius;
- resource consumption;
- upgrade independence;
- network topology;
- storage dependencies;
- management-plane isolation.

A dedicated cluster or dedicated node pool is a valid outcome even if the control plane is technically capable of running elsewhere.

## 8. Storage boundary

OpenStack has two different storage concerns that must not be conflated:

1. persistence for its Kubernetes-hosted control-plane services;
2. tenant-facing block/image storage semantics exposed by Cinder/Glance.

An OpenKubes StorageClass satisfying (1) does not prove that it is an appropriate backend for (2).

The spike must demonstrate the chosen Cinder/Glance profile functionally and document any direct backend dependency such as Ceph/RBD.

## 9. Identity boundary

Keystone is the identity authority for the OpenStack API in the reference implementation.

This does not make Keystone the OpenKubes identity contract.

Federation with an OpenKubes/shared identity provider may be evaluated as an implementation profile, but the first acceptance decision requires only a clear trust and credential boundary. Any federation claim requires its own functional evidence.

## 10. Lifecycle boundary

OpenKubes may automate installation, configuration, reconciliation, upgrade orchestration and removal of `ok-openstack`.

OpenKubes does not redefine OpenStack's internal service upgrade semantics.

A future production profile must pin a supported compatibility matrix and define:

- desired-state source;
- preflight;
- upgrade ordering;
- rollback/recovery boundary;
- evidence invalidation and re-proving;
- teardown behavior.

The first spike need not prove production HA or every upgrade path, but it must identify the boundary honestly.

## 11. Alternatives considered

### A. Make OpenStack the OpenKubes VM layer

Rejected for the proposed architecture. It couples OpenKubes to OpenStack semantics and conflicts with the contract-first principle before a forcing need exists.

### B. Use only KubeVirt and reject OpenStack

Not selected. KubeVirt and OpenStack serve overlapping but different consumer models. The existence of a Kubernetes-native VM API does not answer whether a conventional tenant-facing IaaS API is useful.

### C. Hide both behind a generic VM contract now

Rejected as premature. A lowest-common-denominator abstraction risks losing network, image, tenant and storage semantics without evidence that consumers benefit.

### D. Treat OpenStack-Helm as an ordinary application

Rejected as an assumption. Compute/network components may require privileged, host-coupled behavior that must be made explicit before placement and isolation can be accepted.

## 12. Consequences

### Positive

- OpenKubes can potentially offer conventional IaaS without becoming OpenStack-centric.
- OpenStack remains replaceable at the composition boundary.
- KubeVirt remains available for Kubernetes-native VM consumers.
- Host prerequisites become explicit and testable.
- The architecture can support mixed Kubernetes, AI and IaaS consumers on a shared framework where the constraint envelope permits it.

### Trade-offs

- OpenStack adds substantial operational and security complexity.
- Some implementation requirements may be too host-specific for existing OpenKubes profiles.
- A dedicated node pool or cluster may be required, reducing apparent infrastructure consolidation.
- Two VM-facing models require clear product documentation rather than pretending they are identical.

## 13. Path to acceptance — OK-184

This ADR remains **Proposed** until OK-184 supplies acceptance evidence.

Acceptance requires:

1. a pinned, reproducible OpenStack-Helm reference deployment on an identified OpenKubes constraint envelope, or a precise evidence-backed incompatibility;
2. functional Keystone authentication;
3. functional Nova VM lifecycle;
4. functional tenant networking and the claimed external path;
5. functional Cinder persistence;
6. enumerated host privilege/security requirements;
7. failure/reconciliation evidence;
8. removal/isolation evidence;
9. an evidence-backed placement decision;
10. an explicit conclusion on the KubeVirt/OpenStack relationship without inventing an unsupported common contract.

The spike updates this ADR to **Accepted**, **revised**, or **rejected**. A successful installation alone is not acceptance.

## 14. Non-goals

This ADR does not:

- replace KubeVirt;
- make OpenStack mandatory;
- promise a managed OpenStack SLA;
- define OpenStack APIs as OpenKubes APIs;
- guarantee all OpenStack deployment models;
- define a universal VM abstraction;
- require OpenStack to run on `ok-mgmt`;
- claim production readiness before the evidence exists.

## 15. Working name

`ok-openstack` is a working composition/profile name. Repository or product naming is not decided by this ADR.
