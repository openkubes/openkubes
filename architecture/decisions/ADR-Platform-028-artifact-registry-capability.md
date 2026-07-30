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

That forcing consumer now exists: a central OpenKubes-Family registry on the Shared Cluster that must publish, verify, store, distribute, export, and recover OCI artifacts — container images, OCI Helm charts, multi-architecture indexes, signatures, SBOMs, attestations, provenance, and policy bundles — for connected and air-gapped environments, without the operational footprint of a full enterprise registry before that footprint is justified.

The OCI Distribution Specification is content-type-agnostic, so one standards-based registry contract covers all of the above rather than product-specific repository contracts. Consistent with ADR-Platform-001, the platform must own the required behaviour without making zot, Harbor, Quay, or any future implementation part of the consumer-facing architecture.

## 2. Decision drivers

OCI-standard compatibility; container images and OCI Helm charts; signatures, SBOMs, attestations; connected and air-gapped operation; low initial operational complexity; fit for the Shared Cluster; identity via the OpenKubes OIDC capability (ADR-020); revocable machine access for CI/CD and clusters; immutable, digest-addressable releases; tested backup and recovery; observability via the platform contract; implementation replaceability; no proprietary artifact format or client protocol; and no new registry engine before a demonstrated need.

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

The `registry-default` Implementation Profile MUST integrate with the OpenKubes central OIDC identity capability (ADR-020), the Secret Contract (ADR-Platform-011 §Secret Contract) through its datacenter Implementation Profile (ADR-025), the ingress and certificate capability (ADR-010), the observability capability (ADR-018), GitOps-managed configuration (ADR-011), and a tested backup and recovery procedure (§4.8). Provider-specific mechanisms may differ across future profiles, but the externally observable contract SHALL remain equivalent.

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

ADR-Platform-017 does **not** currently define an `air-gapped` Constraint Envelope — it defines only `datacenter` and `constrained-edge`, and lists air-gapped explicitly as a deferred candidate. The operational offline-transfer proof required by §8 validates the portability and completeness of registry content; it does **not** create or formalize a new Constraint Envelope.

When a real deployment demonstrates materially distinct air-gapped guarantees, a separate ADR SHALL extend ADR-Platform-017 and qualify those guarantees. That later formalization does not block acceptance of this ADR.

This ADR does **not** change ADR-Platform-012's selected golden-PVC flow for Talos boot images. Moving that artifact flow onto the registry requires a separate extension or revision of ADR-Platform-012.

### 4.10 Observability

The `registry-default` profile MUST expose enough signal to monitor service availability, push/pull failures, request latency, storage consumption, failed authn/authz, garbage-collection execution, storage-integrity/scrub failures, backup age, restore-test status, and certificate expiry. Mapping implementation metrics to OpenKubes alerts is part of the profile.

## 5. `registry-default` profile

```text
Profile:     registry-default
Location:    OpenKubes Shared Cluster (ok-shared, ADR-020)
Audience:    OpenKubes Family and internal automation
Management:  GitOps (ADR-011)
Storage:     Production-approved persistent or object storage
Identity:    OpenKubes central OIDC capability (ADR-020)
```

The profile SHALL use a curated zot configuration, not every available extension. Initial feature set: OCI core, authn/authz, metrics, storage-integrity checking, garbage collection, and required search/discovery. Synchronization and an optional UI are included only where a concrete use case exists. Registry-integrated vulnerability scanning MAY be added later; it is not required initially because release security evidence must not depend on an embedded scanner (§4.6).

The profile is owned by an OpenKubes-Family repository (provisionally `ok-artifact-registry`) holding the profile configuration, policies, contract tests, air-gap tooling, and operational docs. It SHALL NOT fork or vendor a complete registry implementation without a separate recorded decision.

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

**Negative / cost.** OpenKubes must maintain provider-neutral contract tests; the zot profile needs OpenKubes-specific tooling for account lifecycle and promotion; the Shared Cluster takes on a critical supply-chain service, so bootstrap and disaster-recovery dependencies need explicit treatment.

**Risks.**

| Risk | Mitigation |
| --- | --- |
| zot misses a required production capability | Acceptance spike + contract tests before adoption |
| zot behaviour leaks into consumers | Contract-first configuration; provider-neutral tests |
| Shared registry becomes a single point of failure | Tested backup/restore, availability and bootstrap design |
| Tags mutated or removed | Digest-based release evidence; immutability policy (§4.7) |
| Registry compromise affects the supply chain | Least privilege, signatures, audit, isolation, recovery |
| Air-gap path diverges from ADR-012 | Reconcile transfer mechanism with ADR-012 during §8 criterion 8 |
| Scope creep to multiple providers | One profile now; add another only for a forcing consumer (§7) |

## 11. Decision summary

OpenKubes defines a product-neutral Artifact Registry Contract and introduces one profile now — `registry-default`, implemented with zot on the Shared Cluster — extending ADR-020 by refining its provisional v1 registry candidate. Harbor, Quay, an external registry, and a native implementation are anticipated paths only, gated by a forcing consumer. `registry-default` is scoped to the `datacenter` envelope; its core OCI guarantees are envelope-invariant. An operational offline-transfer proof is required for acceptance; no `air-gapped` Constraint Envelope exists yet, and its future formalization is not required. The contract owns the required behaviour; no registry product becomes the architecture.
