# ADR-Platform-028: Artifact Registry Capability

- **Status:** Draft — three-way review complete (Arash / Claude / GPT); pending acceptance evidence (§8)
- **Date:** 2026-07-30
- **Decision owners:** OpenKubes Platform Architecture
- **Scope:** OpenKubes Platform
- **Supersedes:** None
- **Extends:** ADR-Platform-020 — refines its provisional v1 registry candidate into a product-neutral Artifact Registry Contract and selects `registry-default` (zot) as the initial implementation (ADR-020 gains the back-reference `Extended by: ADR-Platform-028`)
- **Constraint Envelope:** `datacenter`
- **Related work:** OK-133 — Validate `registry-default` (zot) against ADR-Platform-028
- **Related:**
  - ADR-Platform-001 — OpenKubes owns the contracts, not the components (`Accepted`)
  - ADR-Platform-002 — openkubes/openkubes is the Platform Distribution and Integration Layer (`Accepted`)
  - ADR-Platform-020 — Shared Platform Services Capability (ok-shared) (`Accepted`)
  - ADR-Platform-017 — Constraint Envelopes (`Accepted`) — `registry-default` is scoped to `datacenter`; no `air-gapped` envelope defined yet
  - ADR-Platform-012 — Air-Gapped Image Mirroring for Talos Boot Images (`Proposed`)
  - ADR-Platform-010 — Ingress for OpenKubes Workload Clusters (`Accepted`)
  - ADR-Platform-011 — GitOps for OpenKubes Cluster Lifecycle (`Proposed`)
  - ADR-Platform-018 — Observability Capability — Per-Cluster Stack (`Accepted`)
  - ADR-Platform-025 — Datacenter secret-sync Implementation Profile: Vault on ok-shared + VSO (`Draft`) — profiles ADR-011 §Secret Contract
  - ADR-Platform-023 — CAPI infrastructure providers as Implementation Profiles (`Accepted`) — profile-pattern precedent

---

## 1. Context

ADR-Platform-020 established that a container registry is one of the services `ok-shared` operates once and offers to all clusters, and provisionally named Harbor for that row. It did not define the registry as a contract, and it did not decide the initial implementation against the actual first forcing consumer.

That forcing consumer now exists: a central OpenKubes-Family registry on the Shared Cluster that must publish, verify, store, distribute, export, and recover OCI artifacts — container images, OCI Helm charts, multi-architecture indexes, signatures, SBOMs, attestations, provenance, and policy bundles — for connected environments today, with offline artifact portability as a first-class contract concern and formal air-gapped qualification deferred (§4.9), without the operational footprint of a full enterprise registry before that footprint is justified.

The OCI Distribution Specification is content-type-agnostic, so one standards-based registry contract covers all of the above rather than product-specific repository contracts. Consistent with ADR-Platform-001, the platform must own the required behaviour without making zot, Harbor, Quay, or any future implementation part of the consumer-facing architecture.

## 2. Decision drivers

OCI-standard compatibility; container images and OCI Helm charts; signatures, SBOMs, attestations; connected operation with offline artifact portability (air-gapped qualification deferred, §4.9); low initial operational complexity; fit for the Shared Cluster; identity via the OpenKubes OIDC capability (ADR-020); revocable machine access for CI/CD and clusters; immutable, digest-addressable releases; tested backup and recovery; observability via the platform contract; implementation replaceability; no proprietary artifact format or client protocol; and no new registry engine before a demonstrated need.

## 3. Decision

OpenKubes SHALL define a product-neutral **Artifact Registry Contract** and introduce exactly **one** Implementation Profile now: **`registry-default`**, for the OpenKubes-Family registry service on the Shared Cluster.

The initial `registry-default` profile SHALL be implemented using **zot**. zot is selected because a minimal OCI core is separable from optional extensions and can run as a single statically built binary without mandatory supporting services, while supporting OCI artifacts, Helm charts, signatures, authentication, authorization, garbage collection, metrics, and filesystem- or object-storage-backed operation.

zot-specific APIs, terminology, configuration structures, and extensions SHALL NOT become part of the Artifact Registry Contract. The zot choice is an implementation decision for `registry-default`, not a contract term.

Additional Implementation Profiles SHALL be introduced only for a demonstrated forcing consumer (§7).

```text
Artifact Registry Capability
└── Artifact Registry Contract
    └── registry-default  (Implementation Profile)
        └── implementation: zot
```

## 4. Artifact Registry Contract

### 4.1 Mandatory data-plane behaviour

Any implementation of the contract MUST support: the OCI Distribution API required by supported OpenKubes clients; content-addressable storage by cryptographic digest; push/pull of OCI container images and OCI Helm charts; multi-platform image indexes; retrieval by immutable digest; the **OCI Referrers API** required to discover artifacts associated with a subject digest; TLS-protected communication; authenticated machine access; repository-scoped pull/push authorization; deterministic, automation-suitable error behaviour; and health/readiness reporting.

The contract SHALL be validated against the OCI Distribution conformance tooling where applicable.

### 4.2 Mandatory OpenKubes integration (registry-default)

The `registry-default` Implementation Profile MUST integrate with the OpenKubes central OIDC identity capability (ADR-020), the Secret Contract (ADR-Platform-011 §Secret Contract) through its datacenter Implementation Profile (ADR-025), the ingress and certificate capability (ADR-010), the observability capability (ADR-018), and a tested backup and recovery procedure (§4.8). Provider-specific mechanisms may differ across future profiles, but the externally observable contract SHALL remain equivalent.

The profile SHOULD be managed as GitOps configuration (ADR-011, `Proposed`); manual or Helm-based deployment is acceptable for initial acceptance, with GitOps as the target operating model. GitOps management is therefore not a §8 acceptance gate.

### 4.3 Artifact identity

Immutable digests SHALL be the canonical artifact identity for OpenKubes release evidence. Tags MAY provide discoverability and human-readable versioning, but a mutable tag alone SHALL NOT constitute release evidence. The release manifest SHALL record the digest.

```text
registry.openkubes.internal/openkubes/ok-cluster:v1.4.0
registry.openkubes.internal/openkubes/ok-cluster@sha256:<digest>
```

### 4.4 Namespace model

Consumers SHALL depend on repository paths and artifact references, not on provider project objects. The initial logical namespace is `openkubes/{platform,cluster,observability,security,storage,ai,robotics,applications,third-party,staging,quarantine}/`. Mapping to provider projects, organizations, or access-control constructs is implementation-specific.

### 4.5 Identity and authorization

Human access to `registry-default` MUST use the OpenKubes central OIDC identity capability (ADR-020). Machine access MUST use distinct, revocable, least-scope credentials. A future External-Registry profile MAY define its identity guarantees against its own forcing consumer. These identities MUST remain separate: build, staging publisher, release promoter, cluster pull, air-gap exporter, scanner/verification, registry administrator, break-glass administrator. Shared user credentials SHALL NOT be used for CI/CD or cluster access.

### 4.6 Supply-chain metadata

The registry SHALL let OpenKubes releases associate a signature, SBOM, build provenance, attestation, policy/vulnerability evidence, and release metadata with an artifact digest, using the **OCI Referrers API** and standard OCI artifact types rather than proprietary provider metadata. Migration, backup/restore, and offline transfer MUST preserve these subject→referrer relationships. No registry-integrated scanner SHALL be the sole source of release evidence; security and policy decisions MUST remain reproducible outside any specific registry product.

### 4.7 Retention and immutability

Released artifacts MUST be protected against unintended mutation or deletion. The profile MUST define tag immutability, release/staging/quarantine retention, garbage-collection behaviour, deletion authorization, and an emergency-deletion procedure. Garbage collection MUST NOT remove blobs still reachable from a retained manifest, index, signature, SBOM, or other retained referrer relationship.

### 4.8 Backup and recovery

The `registry-default` profile MUST provide documented, tested recovery for artifact content, registry configuration, authorization configuration, signing/trust configuration, ingress/certificate configuration, and machine identities (or their reproducible re-creation). A configuration backup without artifact-content recovery — or artifact content without the metadata needed to serve and authorize it — is insufficient. Restore evidence MUST include a successful pull by immutable digest after restoration.

### 4.9 Offline-transfer and future air-gapped qualification

The `registry-default` Implementation Profile is scoped to the `datacenter` Constraint Envelope (ADR-Platform-017). The following base-contract guarantees are **envelope-invariant**: immutable-digest retrieval, portable OCI content, artifact enumeration, and preservation of subject-to-referrer relationships. The base contract does not prescribe a provider-specific transfer mechanism.

Per ADR-Platform-017's requirement that a contract address each envelope explicitly: the Artifact Registry Contract governs a datacenter-hosted shared service; `constrained-edge` clusters are **consumers (pull clients)** of that service, not registry hosts, so no `constrained-edge` Implementation Profile is defined.

ADR-Platform-017 does **not** currently define an `air-gapped` Constraint Envelope — it defines only `datacenter` and `constrained-edge`, and lists air-gapped explicitly as a deferred candidate. The operational offline-transfer proof required by §8 validates the portability and completeness of registry content; it does **not** create or formalize a new Constraint Envelope.

When a real deployment demonstrates materially distinct air-gapped guarantees, a separate ADR SHALL extend ADR-Platform-017 and qualify those guarantees. That later formalization does not block acceptance of this ADR.

This ADR does **not** change ADR-Platform-012's selected golden-PVC flow for Talos boot images. Moving that artifact flow onto the registry requires a separate extension or revision of ADR-Platform-012.

### 4.10 Observability

The `registry-default` profile MUST expose enough signal to monitor service availability, push/pull failures, request latency, storage consumption, failed authn/authz, garbage-collection execution, storage-integrity/scrub failures, backup age, restore-test status, and certificate expiry. Mapping implementation metrics to OpenKubes alerts is part of the profile.

### 4.11 Consumer trust and endpoint resolution

The contract mandates TLS (§4.1) and authenticated machine access (§4.5) but has so far said
nothing about how a consumer *obtains* trust in that endpoint or *resolves* its name. Onboarding
is therefore recorded here, because it is a real cost the contract was silently omitting.

**Contract boundary.** The registry SHALL publish a TLS endpoint with a certificate valid for its
published name. Establishing trust in that certificate's issuer, and resolving that name, are the
**consumer's** responsibility, not the registry's. The registry MUST NOT weaken TLS, offer a
plaintext fallback, or assume any particular consumer trust mechanism.

**`registry-default` choice.** The profile is served from the Shared Cluster's internal CA rather
than a publicly-trusted certificate: the service is internal by design, and a public certificate
would buy exposure and cost for no reachability the estate needs. Consumers integrate **opt-in per
cluster**, at cluster-creation time, rather than by a fleet-wide trust-store push. Not every
cluster will ever pull from this registry, and a blanket distribution would bake in an assumption
that does not hold.

This is deliberately scoped to the registry. It is **not** a general platform policy for shared
services, and it does not resolve ADR-Platform-020's deferred PKI question. ADR-020 defers
platform-wide trust management until a capability requires *platform-wide* trust; what this
capability required was endpoint-scoped trust for individual opting-in consumers, so that trigger
did not fire and no ADR-020 capability row is owed. Should a second shared service later need the
same treatment, the generalisation should be argued from those two cases rather than anticipated
from this one.

Stated precisely, because a looser phrasing would mislead: the estate has a **central trust root
and central issuance** — `ok-shared-internal-ca` is a cluster-wide issuer already reused by Vault,
Keycloak and now the registry. What it does not have, and what this section declines to introduce,
is **fleet-wide trust distribution**.

**Mechanism.** The reusable building block lives in `ok-cluster` (`docs/registry-trust.md`),
which owns the Talos specifics, the runtime procedure and the recreate/recovery considerations.
Those mechanics are deliberately not restated here; this ADR records only the decision and its
costs.

**Costs**, none of which were previously written down:

- The registry is offered to every cluster but usable only after that cluster opts in, so
  availability and reachability are not the same property here.
- The mechanism is Talos-specific. No equivalent is established for other node profiles.
- Static host entries are interim resolution: every opted-in cluster needs reconciling whenever
  the ingress address changes, until OK-57 delivers DNS for the internal zone.
- CA rotation means redistributing the root to every opted-in consumer.
- Because the Shared Cluster was patched at runtime rather than rebuilt, replacement Machines
  (autoscaling, node replacement, reset) do not inherit trust and need the procedure rerun until
  the cluster is recreated from an opted-in manifest.
- Recreating the Shared Cluster *itself* with consumer trust enabled from the start cannot work in
  one pass: the CA and the registry do not exist at first bootstrap. That case needs
  bootstrap-then-apply; the building block serves a **new consumer** trusting an
  **already-running** registry.

**Proof boundary.** The kubelet-pull acceptance evidence (§8.3) was produced on the Shared Cluster
itself, so it proves the Talos runtime mechanism and the host/SNI path but not consumer onboarding.
That remaining gap has since been closed: `ok-ai` was onboarded as the first cluster other than the
Shared Cluster to trust the registry, running the full review → dry-run → apply sequence across all
four of its CAPI Machines with read-back confirmed on each, then pulling a digest-pinned image
whose kubelet `Pulled` event and `imageID` matched exactly.

Onboarding a genuinely distinct cluster is what made the gap worth recording, because it surfaced a
defect that self-onboarding structurally could not: the trust tooling silently reused the CA
kubeconfig as the workload-cluster kubeconfig for Node lookups. On the Shared Cluster those are the
same file, so the bug was invisible there and would have stayed invisible for as long as the
capability was only ever proven against itself. The tooling now requires an explicit workload
kubeconfig and fails closed without one, and the repeatable procedure lives in `ok-cluster`
(`docs/registry-onboard-cluster.md`) rather than being re-derived per cluster.

Still unexercised: onboarding a node profile other than Talos, for which no equivalent mechanism is
established.

## 5. `registry-default` profile

```text
Profile:     registry-default
Location:    OpenKubes Shared Cluster (ok-shared, ADR-020)
Audience:    OpenKubes Family and internal automation
Management:  GitOps (ADR-011) — target; manual/Helm acceptable for initial acceptance
Storage:     Production-approved persistent or object storage
Identity:    OpenKubes central OIDC capability (ADR-020)
```

The profile SHALL use a curated zot configuration, not every available extension. Initial feature set: OCI core, authn/authz, metrics, storage-integrity checking, garbage collection, and required search/discovery. Synchronization and an optional UI are included only where a concrete use case exists. Registry-integrated vulnerability scanning MAY be added later; it is not required initially because release security evidence must not depend on an embedded scanner (§4.6).

The profile is owned at `openkubes/platform/registry/zot/`, which SHALL hold the profile configuration, policies, contract tests, air-gap tooling, and operational docs. It SHALL NOT fork or vendor a complete registry implementation without a separate recorded decision.

## 6. Anticipated implementation paths (not contracted, not maintained)

The following are documented for direction only. "Anticipated" does not mean supported, contracted, or maintained. Each becomes a candidate profile only under §7.

- **Harbor** — evaluated when delegated multi-team governance, quotas, and self-service become a forcing requirement. (This is the implementation ADR-020 provisionally assumed; it is not the initial default.)
- **Quay** — evaluated for an OpenShift-specific forcing consumer.
- **External registry** — introduced when a customer integration requires reuse of an existing conforming OCI registry; validated through the same consumer-facing contract tests.
- **OpenKubes-native registry** — a potential future OpenKubes-native implementation, researched only after existing implementations demonstrably fail a proven requirement. No product name is reserved by this ADR.

## 7. Gate for additional profiles

A new Implementation Profile SHALL be added only when a consumer demonstrates that `registry-default` cannot meet a concrete requirement, that the requirement belongs in the registry implementation rather than a surrounding OpenKubes workflow, and that long-term conformance, security, upgrade, and operational ownership are funded. A native implementation additionally requires that it can remain OCI-conformant and that migration to and from another conforming registry stays possible.

## 8. Acceptance criteria

This ADR remains `Draft` until `registry-default` (zot) demonstrates:

1. image push and pull;
2. OCI Helm chart push and pull;
3. pull by at least one Kubernetes workload;
4. immutable-digest references in release evidence;
5. storage and retrieval of an SBOM or signature via the Referrers API;
6. OIDC identity integration (ADR-020) and repository authorization for human and machine identities;
7. metrics collection, backup and restore, and an upgrade/rollback test;
8. **operational** offline transfer of a representative OpenKubes release — export, integrity/completeness verification, import, and pull by digest — as an operational proof; no `air-gapped` Constraint Envelope exists yet (ADR-017), and its future formalization is not required for acceptance;
9. the applicable OCI Distribution conformance tests;
10. documented bootstrap and disaster-recovery procedures;
11. acceptance evidence recorded in OK-133.

After review of this evidence, the ADR MAY transition to `Accepted`.

## 9. Alternatives considered

- **Harbor as the initial default** — mature governance and robot-account model, but a larger operational and metadata footprint than the first Family service needs, and higher risk of Harbor concepts leaking into the contract. Not selected initially; retained as an anticipated path.
- **Quay as the initial default** — strong OpenShift and disconnected-operation capabilities, but stronger OpenShift alignment and more operational complexity than a distribution-neutral default warrants. Not selected; retained as an anticipated path.
- **External registry only** — no OpenKubes-operated registry, but no canonical Family store, inconsistent workflows, and a hard dependency on customer infrastructure; insufficient where no registry exists. Supported as an integration path, not as the only model.
- **Develop a native registry now** — full control, but substantial security/maintenance burden and OCI-conformance cost, duplicating mature implementations before a unique requirement is proven. Rejected for now; gated per §7.
- **No shared registry** — no new shared component, but continued dependence on public registries, no controlled release store, no reliable air-gap path, and weaker supply-chain governance. Rejected.

## 10. Consequences

**Positive.** A shared OCI artifact-distribution capability with a small initial footprint; consumers independent of zot behaviour; offline artifact portability treated as a first-class contract concern, with future air-gapped guarantees qualified through the ADR-017 mechanism; reusable conformance tests; a future native implementation possible without changing consumer references or artifact formats.

**Negative / cost.** OpenKubes must maintain provider-neutral contract tests; the zot profile needs OpenKubes-specific tooling for account lifecycle and promotion; the Shared Cluster takes on a critical supply-chain service, so bootstrap and disaster-recovery dependencies need explicit treatment; and each consuming cluster carries its own onboarding cost, because trust and name resolution are opt-in per cluster rather than fleet-wide (§4.11).

**Risks.**

| Risk | Mitigation |
| --- | --- |
| zot misses a required production capability | Acceptance spike + contract tests before adoption |
| zot behaviour leaks into consumers | Contract-first configuration; provider-neutral tests |
| Shared registry becomes a single point of failure | Tested backup/restore, availability and bootstrap design |
| Tags mutated or removed | Digest-based release evidence; immutability policy (§4.7) |
| Registry compromise affects the supply chain | Least privilege, signatures, audit, isolation, recovery |
| Air-gap path diverges from ADR-012 | Reconcile transfer mechanism with ADR-012 during §8 criterion 8 |
| Opted-in consumers drift as the ingress address or CA changes | Address discovery re-resolves on every run; CA rotation and replacement Machines require the onboarding procedure to be rerun (§4.11) |
| Scope creep to multiple providers | One profile now; add another only for a forcing consumer (§7) |

## 11. Decision summary

OpenKubes defines a product-neutral Artifact Registry Contract and introduces one profile now — `registry-default`, implemented with zot on the Shared Cluster — extending ADR-020 by refining its provisional v1 registry candidate. Harbor, Quay, an external registry, and a native implementation are anticipated paths only, gated by a forcing consumer. `registry-default` is scoped to the `datacenter` envelope; its core OCI guarantees are envelope-invariant. An operational offline-transfer proof is required for acceptance; no `air-gapped` Constraint Envelope exists yet, and its future formalization is not required. The contract owns the required behaviour; no registry product becomes the architecture.
