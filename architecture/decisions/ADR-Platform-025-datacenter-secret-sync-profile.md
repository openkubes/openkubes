# ADR-Platform-025: Datacenter secret-sync profile — Vault on ok-shared + Vault Secrets Operator (VSO)

**Status:** Draft — three-way review complete (Arash / Claude / GPT, 2026-07-25), approved for commit as Draft. Stays Draft until the acceptance evidence below.
**Date:** 2026-07-25
**Implements / profiles:** ADR-Platform-011 §Secret Contract (OK-71)
**Related:** ADR-Platform-013 (registration/trust), ADR-Platform-020 (Shared Platform Services), ADR-Platform-018 (observability autonomy), OK-110, OK-109, OK-81

---

## Context

The Secret Contract (ADR-011 amendment, OK-71) makes the secret **tool** a per-envelope **Implementation Profile**, not part of the contract. This ADR fixes the **datacenter-envelope profile** only. Constrained-edge / air-gapped keeps the offline-reconcilable (SOPS / Sealed-class) profile — already realised by ok-observability's phase-1 file Secret, unchanged. No Vault server or secrets-sync operator exists yet on any live cluster (OK-109 pass, 2026-07-25). This is an Implementation Profile decision, **not a new contract**.

## Decision

Datacenter-envelope secret-sync profile = **HashiCorp Vault on ok-shared**, consumed via the **Vault Secrets Operator (VSO)** on each datacenter cluster.

- **Backend:** Vault on ok-shared. ADR-025 authorizes Vault as a **bounded first shared service required by the Secret Contract**; it does **not** implicitly activate or accept the broader Shared Platform Services capability (OK-81).
- **Operator:** VSO; secrets materialise as native Kubernetes Secrets via `VaultStaticSecret`.
- **Sync baseline:** **periodic reconciliation via `refreshAfter`, compatible with Vault Community.** Vault Enterprise event notifications (`instantUpdates`) may *optionally* reduce propagation latency but are **not required for conformance**; `refreshAfter` remains configured regardless (event delivery is not guaranteed).
- **Trust model:** one **Kubernetes auth *mount* per consuming cluster**, named by the ADR-013 cluster id (`auth/kubernetes/<cluster-name>`) — a mount binds exactly one API server / CA / token-reviewer context. Within the mount, Vault **roles and policies are scoped per namespace / workload identity**, not merely per cluster. Two levels: the cluster id selects the mount (which API server); the role/policy is the actual authorization.
  - A shared cluster-wide VSO ServiceAccount **MUST NOT** become the effective identity of all secret consumers: each application or bounded workload receives its **own** ServiceAccount, Vault role, and least-privilege policy. `VaultAuthGlobal` may share connection and mount configuration, but **MUST NOT** collapse workload authorization.
  - **Authentication topology — decided (OK-110):** chosen primarily by network topology, then by credential-lifecycle and revocation requirements. See §"Authentication topology (decided — OK-110)" below.
- **Reference consumer:** `ok-observability-credentials` produced by a `VaultStaticSecret`, applied **before** the observability Helm release (OpenSearch 2.12+ needs the admin password at start) — **no chart change**.

## Authentication topology (decided — OK-110)

The auth mode between a workload cluster and the central Vault on ok-shared is chosen **primarily by network topology, then by credential-lifecycle and revocation requirements** — a three-tier cascade that minimises Day-2 maintenance (key rotation) while respecting network restrictions. (For VSO the consuming cluster must at minimum reach Vault; a truly air-gapped cluster is out of this datacenter profile and uses the offline/edge Secret profile instead.)

| Network scenario | Auth mode | Lifecycle consequence |
|---|---|---|
| **A — Same SDN / no restrictive firewall.** Bidirectional Vault ↔ cluster-API allowed. | **Kubernetes auth** (dedicated mount per cluster, `auth/kubernetes/<cluster>`) | Preserves Kubernetes-native TokenReview and early-revocation semantics. Requires Vault → cluster API (6443) reachability **and** an explicit reviewer-credential model: either a lifecycle-managed reviewer JWT, or use of each client JWT for TokenReview with the required `system:auth-delegator` permission. **Not maintenance-free.** |
| **B — Unidirectional.** Vault cannot reach the cluster API, but a JWKS endpoint is reachable (directly or via an object-store / pushed mirror). | **JWT auth with OIDC discovery or JWKS URL** | Vault re-fetches the published JWKS automatically. For a pushed / object-store mirror, publication freshness and old/new-key overlap remain explicit operational responsibilities. Short-lived projected tokens required (JWT auth does not observe early Kubernetes revocation). |
| **C — API-isolated / workload-to-Vault only.** The consuming cluster can reach Vault, but Vault can reach neither the cluster API nor a cluster-maintained JWKS endpoint. | **Pinned validation keys (static)** | Purely cryptographic validation against the cluster's pinned public keys. **Hard acceptance gate — see below.** |

**Current scope (ok-robotics):** ok-robotics and ok-shared are in the same SDN without restrictive firewalls → **Category A**. Selected subject to proving **both** the network path (Vault → TokenReview on 6443) **and** the reviewer-credential model — network reachability alone is **not** sufficient acceptance evidence. A dedicated mount per cluster; a shared cluster-wide role is explicitly excluded.

**Category C is gated** — the pinned-keys profile MUST NOT be activated until:
1. a **key-overlap procedure** is in the GitOps process (Vault holds the old *and* new public key across the cluster's certificate-rotation window),
2. **short-lived projected tokens** are enforced, and
3. **alerting on silent auth breakage** is in place — on the observable symptom (consuming `VaultAuth` / `VaultStaticSecret` `Healthy=false` / `VaultAuth.status.valid=false`, and/or a synthetic periodic login probe) plus Vault audit-log auth failures; not on a single vendor telemetry metric that may not exist for the chosen method.

The pinned public keys are **cluster-originated** and count as part of the Vault-independent bootstrap origin, so the bootstrap invariant is preserved.

## Cross-cluster reachability (decided — OK-110)

Consumers reach the central Vault via the **ok-shared Traefik ingress**, modeled as an `IngressRouteTCP` with **TLS passthrough** and `HostSNI(vault.ok-shared.internal)`, backed by the leader-only **`vault-active`** service. This supersedes the manual host-cluster LoadBalancer proxy used in the PoC and reduces **OK-57** to an optional simplification rather than a prerequisite for this consumer.

- **Passthrough, not termination.** Vault is a secret backend: TLS is end-to-end so Vault sees the real client and its audit log is meaningful; there is no plaintext hop inside ok-shared. This **supersedes the earlier "no TLS" scaffold note** — server TLS is in scope for the datacenter profile.
- **`vault-active` backend (leader-only).** Routing to the plain `vault` service can hit a Raft standby, which answers with a 307 redirect to the leader's internal `api_addr` — a cross-cluster consumer cannot follow an internal redirect target. `vault-active` selects only the leader, avoiding the redirect (Vault Community has no performance standbys; all reads go to the leader anyway).
- **Server TLS trust origin.** The Vault server certificate is issued by a cert-manager **internal CA** (`ok-shared-internal-ca`, self-signed bootstrap Issuer → CA → server cert), a **Vault-independent** origin — consistent with the bootstrap invariant (TLS trust for the Vault endpoint must not come from Vault itself). Not Let's Encrypt: `vault.ok-shared.internal` is not a public zone, so ACME/HTTP-01 cannot validate it.
- **Consumer-side obligations.** Each datacenter consumer cluster (e.g. `ok-robotics`) needs (1) a **CoreDNS** entry resolving `vault.ok-shared.internal` to the ok-shared ingress MetalLB IP — the SNI host, not just the IP, must match because passthrough routes on SNI; and (2) the internal CA bundle wired into VSO via `VaultConnection.caCertSecretRef` + `tlsServerName`.

Artifacts: `platform/secrets/vault/crossplane/reachability.yaml` (internal CA + server cert + `IngressRouteTCP`). Enabling the Vault server TLS listener itself (mount `vault-server-tls`, https Raft `retry_join`) is a separate, reviewable Composition change; passthrough is inert until Vault serves TLS.

## Rationale (VSO over ESO)

Chosen because OpenKubes commits to Vault as *the* datacenter backend, and VSO offers **first-party HashiCorp support, Vault-native CRDs and auth, built-in `rolloutRestartTargets`, and support for KV + PKI + dynamic engines** (the direct ESO Vault provider is KV-centric and delegates other engines to separate generators). The rationale rests on *native / first-party / operational fit*, **not** on event-driven sync (which is Enterprise-only).

## Accepted trade-off (declared, not silent)

VSO is **single-provider (Vault-locked)**: it narrows the **datacenter** profile to Vault; a later backend change means an operator swap. Accepted because Vault is the chosen DC backend. Contract-neutral per OK-71 — the lock-in is scoped to the DC profile; edge/offline and future envelopes remain free.

## Alternatives considered

| Alternative | Why not (for the DC profile) |
|---|---|
| **ESO** | Provider-neutral / multi-cloud, has `CreatedOnce` / `Periodic` / `OnChange` policies, but provider-side changes still rely on periodic refresh and the `ExternalSecret` API has **no `rolloutRestartTargets` equivalent** (restart orchestration would be separate). Rejected *for the DC profile* since the backend is fixed to Vault; remains a valid alternative profile the contract permits. |
| **SOPS / Sealed-class** | The constrained-edge / offline profile, not a central-store DC profile. |
| **Keep file-based everywhere** | Fine for edge; forfeits central custody / rotation for DC clusters. |

## Reference consumer — scope of the proof (important)

The observability credential proves **provisioning and migration**, **not** generic rotation:

- **Fresh install:** Vault provides the initial credential **before** the Helm release.
- **Existing-install migration:** the existing credential is **imported unchanged** into Vault — not regenerated (OpenSearch's `OPENSEARCH_INITIAL_ADMIN_PASSWORD` only bootstraps a *new* security index; changing it on an existing cluster is not picked up by a new Secret + restart).
- **Rotation:** needs an application-specific, **coordinated** process; `rolloutRestartTargets` alone is **not** sufficient (a restart does not change the already-persisted OpenSearch admin credential, and an uncoordinated change would leave Fluent Bit on the new value while OpenSearch still expects the old).
- **Reference rotation test:** must use an **actually rotatable** credential, not the OpenSearch bootstrap password.

> The observability credential is the reference consumer for provisioning and migration, not evidence that every bootstrap credential is safely rotatable through Secret replacement and workload restart alone.

## Autonomy & failure behavior (ADR-018)

Vault is a **soft runtime dependency but a hard bootstrap-and-recovery dependency**:

- Already-materialised Kubernetes Secrets + running workloads survive a **temporary** Vault outage.
- Rotation, drift-recovery, reinstall, cluster-rebuild, and restoring a **deleted** Secret require ok-shared / Vault.
- Consistent with OK-71 clause 3 (external store valid only where the envelope guarantees connectivity) and **not** in conflict with ADR-018 autonomy, which the edge/offline profile continues to satisfy.
- **Required test:** cut the Vault connection, verify existing observability workloads + a pod restart survive, then verify reconciliation after Vault returns.

## Bootstrap invariant (acceptance blocker, not a mere open item)

> **Vault and VSO must never be required to establish the credentials or trust material needed to bootstrap Vault itself.**

A Vault-independent origin is required for: init + unseal, TLS trust for the Vault endpoint, initial admin / recovery credentials, auth mounts, policies / roles, and the first secret values (or their migration).

## Kubernetes-Secret threat model

VSO materialises **native Kubernetes Secrets**, so existing requirements remain in force: **etcd encryption at rest, RBAC, namespace isolation, audit**. VSO's **persistent client cache stays disabled** unless its Vault-Transit encryption is explicitly configured (it is not auto-enabled).

## Consequences

- Consumer charts unchanged; the stack + Contract Test Gate stay green with Vault-materialised credentials (re-verified via OK-109 / ADR-024).
- ok-cluster gains a **datacenter-only** step to ensure the `VaultStaticSecret` exists before helm; the edge/offline path is untouched.

## Implementation & placement

Deploys the production Vault + VSO profile by **reusing the existing Crossplane deployment structure**, introducing **no new repository or platform capability contract** (OK-81 stays parked; Vault is a *bounded singleton* implementation profile). An XRD/Composition/XR is itself new API structure — kept deliberately **internal**.

### Deployment vehicle — Crossplane, internal singleton XR (decided)

Deployed by a Crossplane Composition (provider-helm `Release`) applied from **ok-mgmt** onto **ok-shared**, reusing the mechanism proven by `OpenRMFClaim` / `OpenWebUIClaim` (cluster name = join key via a named `ProviderConfig`, ADR-013).

- Modeled as a **cluster-scoped `VaultInstance` XR with NO `claimNames`** — exactly one instance `ok-shared-vault`. **Not** a self-service `Claim` (Claims expose consumable capabilities; Vault is a bounded singleton) — no public `VaultInstanceClaim` API until a second legitimate instance consumer exists.
- The singleton invariant is verified by a **conformance / admission check**: no second production `VaultInstance` may exist while `ok-shared-vault` is active (an internal XRD does not by itself enforce a single instance).
- *Alternative:* an ok-shared bootstrap script — rejected (imperative, off the GitOps trajectory).

### Readiness — Helm-deployed ≠ Vault-ready (invariant)

`VaultInstance Ready=True` **MUST NOT** be derived from provider-helm's `Release=deployed` alone (Vault may be uninitialised, sealed, without Raft quorum / TLS / audit). Expose or gate distinct states: `Installed`, `Initialized`, `Unsealed`, `RaftHealthy`, `TLSReady`, `AuditEnabled`, `Configured`. If the first Composition can observe only the Helm state, it reports **only `Installed`**; a **separate deterministic health gate** supplies acceptance evidence — mirroring the observability contract-test-gate discipline.

### Storage & failure domains

Vault uses **Integrated Storage (Raft)**. The `storageClass` in `VaultInstance` MUST be a StorageClass that exists **inside ok-shared**. The host-cluster `ok-storage` layer may protect the underlying KubeVirt VM disks, but it is **not** itself a workload-cluster StorageClass. The full durability chain MUST be declared and tested:

`Vault Raft replica → ok-shared PVC / node affinity → workload-node disk → KubeVirt VM disk → host ok-storage durability`

If the initial profile uses workload-cluster `local-path`, the ADR states its PVCs are node-affine and **not** independently replicated: Raft provides service-level replication, host storage protects the VM disk — neither silently substitutes the other.

Vault pods MUST be spread across distinct ok-shared nodes (anti-affinity). Replica count is bound to an explicit failure budget: **3 voters → quorum 2, tolerates 1 down; 5 voters → quorum 3, tolerates 2 down.** The chosen count + accepted budget are versioned production config, not chart defaults. Backups use **Vault Raft snapshots** stored outside the Vault cluster's own failure domain (PVC/VM snapshots alone are **not** the normative Vault backup); a restore rehearsal is required before acceptance.

### Artifact placement

| Artifact | Home | Notes |
|---|---|---|
| `VaultInstance` XRD + Composition (provider-helm `Release`, versioned) | `openkubes` (platform) | internal singleton XR; reconciled from ok-mgmt onto ok-shared |
| **Non-secret production config** — HA/Raft, replicas, StorageClass (**inside ok-shared**; see Storage), volume sizes, TLS/ingress (`vault.ok-shared.internal`), seal type, audit storage, auth-mount names, policies, roles, network params | **versioned** in the `VaultInstance` XR / a tracked values doc in `openkubes` | committed & reviewable — **NOT** git-ignored provider values |
| **Offline custody material** — Shamir unseal/recovery shares + PGP-encrypted initial root token | offline, multi-custodian origin independent of Vault **and** Kubernetes | root token is ceremony-only, destroyed after evidenced revocation |
| **Operational bootstrap secrets** — TLS private key, token-reviewer credential, Transit token, HSM PIN/creds | Vault-independent secret origin/delivery; never Git, never dependent solely on this Vault | may come from an external PKI, cert-manager, Kubernetes, HSM/KMS — not necessarily offline human custody |
| VSO cluster add-on | pinned **ok-cluster** install target | explicit, versioned |
| Consumer `VaultStaticSecret` for `ok-observability-credentials` | **ok-cluster**, applied **before** observability helm | ADR-024/025; no chart change; = OK-109 Part 2 |
| Per-cluster auth: dedicated mount + roles + least-privilege policies + reviewer credential | **central declarative Vault reconciler**, triggered by cluster **registration** (ADR-013) | see "Vault configuration" |

### Lifecycle safeguards (production)

- The composed `Release` uses **`deletionPolicy: Orphan`**. **Deleting the XR MUST NOT uninstall Vault or delete its persistent data** — teardown is a separate, evidence-based decommission process.
- The XRD sets **`spec.defaultCompositionUpdatePolicy: Manual`**; the production XR is pinned to an explicitly promoted `CompositionRevision` (field layout per the deployed Crossplane version; Crossplane otherwise auto-adopts newer revisions).
- **Revision identity** includes: Composition revision, provider-helm version, Vault chart version, Vault image version/digest, versioned values, Vault-config revision (extends ADR-024's revision-identity invariant).

### Seal / unseal — bound to the recovery SLO

- **Phase-1 attended-production baseline: manual Shamir unseal, offline multi-custodian custody** — OpenKubes **accepts a manual-recovery SLO for Phase 1** (attended re-unseal after restart; on 3-node Raft, every rescheduled pod → no unattended recovery after a full restart). Init with **PGP-encrypted shares + PGP-encrypted root token**; use the root token only to enable audit, admin auth and the automation identity, then **revoke it** (evidenced). Acceptance requires a **cold-restart rehearsal** recording achieved recovery time, confirming the unseal threshold can be met under the operating model, and that every required Raft voter returns to service.
- **Committed follow-up (not merely conditional):** unattended recovery **will** become a production requirement. When it does, Shamir is insufficient and auto-unseal from an **independently bootstrapped** origin is a blocking prerequisite: Transit (edition-neutral; adds a second Vault + renewable-token lifecycle; no Vault→Vault recursion) or PKCS#11/HSM (Vault Enterprise). The probable sovereign endpoint is HSM/Enterprise or a dedicated KMS/transit appliance.

### Vault configuration — one declarative reconciler, two phases

1. **Bootstrap ceremony** (once, supervised): init, unseal, audit device, initial admin auth, automation identity, root-token revocation.
2. **Day-1/Day-2 reconciliation** (declarative): auth mounts, policies, roles, secret engines, per-registered-cluster config — through **exactly one** reconciler; production auth config MUST NOT be split across multiple authoritative reconcilers.

**Open implementation sub-decision — required before the first production consumer:** select exactly one Day-1/Day-2 reconciler and record: execution owner + trigger; state location + recovery; automation auth method; least-privilege policy; drift detection; concurrency + retry semantics; credential rotation + break-glass. Terraform (vault provider) and an idempotent configuration controller remain candidates; a config Job is acceptable only if all of the above are defined. The automation identity is least-privilege and short-lived (no broad standing credential).

### Decisions requiring ownership

1. **Recovery class** — *decided:* attended Shamir (offline custody) for Phase 1; unattended auto-unseal is a committed follow-up.
2. **Failure budget** — *open (acceptance-gated):* 3 voters (tolerate 1) vs 5 voters (tolerate 2). A 3-node controlled pilot is defensible **as an accepted risk**, not an implicit chart default.
3. **Declarative reconciler** — *open (acceptance-gated):* one authoritative Day-1/Day-2 mechanism incl. its state + automation identity.

The `VaultInstance` XRD/Composition scaffold may begin now provided it does not silently choose defaults for the open items; production VSO onboarding waits on the reconciler decision.

## Path to acceptance (evidence required before `Accepted`)

1. **Mandatory reconciliation settings** defined and tested: `refreshAfter` is always configured; Enterprise `instantUpdates`, if enabled, remains an optional latency optimization, not a conformance dependency. (Edition itself is a deployment/ops choice, not an acceptance gate.)
2. **Auth mount per cluster** + workload-scoped roles/policies implemented.
3. **Authentication topology applied per cluster** using network topology, credential lifecycle, and revocation requirements:
   - **Category A:** Vault→TokenReview reachability proven, and the reviewer-credential model documented and tested without granting unintended cluster-wide privilege.
   - **Category B:** OIDC discovery or JWKS reachable; for a mirrored JWKS, publication freshness and old/new-key overlap tested.
   - **Category C:** activated only with the key-overlap procedure, short-lived projected tokens, synthetic auth-failure detection, and CR-status / audit-log alerting in place.
4. **Unseal / HA / backup / restore** strategy set, and **restore tested**.
5. Vault bootstrap works **without Vault/VSO recursion** (invariant above).
6. An **existing** observability install migrated **without credential change**.
7. A **fresh** install receives the Secret **before** the Helm release.
8. **Vault outage + reconciliation** tested (ADR-018 test above).
9. **Rotation** proven with an actually-rotatable consumer (not the OpenSearch bootstrap password).
10. ADR-024 / OK-109 Contract Gate re-runs **green** with the materialised Secret.
11. **Failure budget decided** (3 vs 5 voters, accepted risk) + pod anti-affinity across ok-shared nodes; **Vault Raft snapshot** backup outside the cluster's failure domain, with a **restore rehearsal** completed.
12. **Cold-restart rehearsal** recorded: recovery time, unseal threshold met under the operating model, all required Raft voters returned to service.
13. **Exactly one Day-1/Day-2 Vault-config reconciler selected** and documented (state, least-privilege automation identity, drift, retry, rotation/break-glass).
14. **Singleton invariant enforced** (conformance/admission check — no second production `VaultInstance`).
15. **Non-manual cross-cluster reachability** proven: consumer reaches Vault over the ok-shared ingress `IngressRouteTCP` (TLS passthrough, `HostSNI(vault.ok-shared.internal)`, `vault-active` backend) with cert-manager server TLS and consumer-side CoreDNS + CA trust — replacing the PoC's manual host-cluster LB proxy.

## Re-evaluation triggers

- A second datacenter secret backend becomes required → revisit the single-provider trade-off.
- The edge profile needs central visibility → separate ADR (does not change this one).
