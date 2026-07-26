# ADR-Platform-025: Datacenter secret-sync profile — Vault on ok-shared + Vault Secrets Operator (VSO)

**Status:** Draft — three-way review complete (Arash / Claude / GPT, 2026-07-25), approved for commit as Draft. Amendments A1–A7 and A10 folded in 2026-07-26 (A6 implementation landed earlier via PR #23; its normative rules are now in-body, evidence in the A6 acceptance record). Stays Draft until the acceptance evidence below — fresh-install (criterion 7) and Vault-outage (criterion 8) remain **open blockers** per the A8/A9 decisions (both kept as blockers).
**Date:** 2026-07-25
**Implements / profiles:** ADR-Platform-011 §Secret Contract (OK-71)
**Related:** ADR-Platform-013 (registration/trust), ADR-Platform-020 (Shared Platform Services), ADR-Platform-018 (observability autonomy), OK-110, OK-109, OK-81

---

## Context

The Secret Contract (ADR-011 amendment, OK-71) makes the secret **tool** a per-envelope **Implementation Profile**, not part of the contract. This ADR fixes the **datacenter-envelope profile** only. Constrained-edge / air-gapped keeps the offline-reconcilable (SOPS / Sealed-class) profile — already realised by ok-observability's phase-1 file Secret, unchanged. No Vault server or secrets-sync operator exists yet on any live cluster (OK-109 pass, 2026-07-25). This is an Implementation Profile decision, **not a new contract**.

## Decision

Datacenter-envelope secret-sync profile = **HashiCorp Vault on ok-shared**, consumed via the **Vault Secrets Operator (VSO)** on each datacenter cluster.

- **Backend:** Vault on ok-shared, **selected by this datacenter implementation profile under the Secret Contract** (ADR-011 permits Vault as a per-envelope profile; it does **not** require Vault). ADR-025 accepts **one bounded shared singleton** for the datacenter Secret profile. It does **not** establish a Shared Platform Services Contract, a `TYPE=shared` lifecycle, an `ok-shared` capability repository, or acceptance of **ADR-020** (which stays Draft) — the broader Shared Platform Services capability (OK-81) stays parked.
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

**Current reachability profile — Path A (host-level LoadBalancer).** Consumers reach the central Vault over a **stable host-cluster LoadBalancer address (`192.168.100.207`), allocated by MetalLB running on `ok-infra` (the host cluster), not in the child cluster** (the `ok-mgmt-lb` pattern; **child clusters run no MetalLB**). The host LoadBalancer forwards TCP/443 to the **ok-shared Traefik** entrypoint (NodePort 30443); Traefik routes the connection as an `IngressRouteTCP` with **TLS passthrough** and `HostSNI(vault.ok-shared.internal)`, backed by the leader-only **`vault-active`** service. TLS is **end-to-end**; the host layer does not terminate or inspect Vault traffic. This is the accepted **Path A** — it replaces the *manual* host-cluster LB proxy used in the PoC and reduces **OK-57** (native child-cluster LB, Path B below) to an optional simplification rather than a prerequisite for this consumer.

- **Passthrough, not termination.** Vault is a secret backend: TLS is end-to-end so Vault sees the real client and its audit log is meaningful; there is no plaintext hop inside ok-shared. This **supersedes the earlier "no TLS" scaffold note** — server TLS is in scope for the datacenter profile.
- **`vault-active` backend (leader-only).** Routing to the plain `vault` service can hit a Raft standby, which answers with a 307 redirect to the leader's internal `api_addr` — a cross-cluster consumer cannot follow an internal redirect target. `vault-active` selects only the leader, avoiding the redirect (Vault Community has no performance standbys; all reads go to the leader anyway).
- **Server TLS trust origin.** The Vault server certificate is issued by a cert-manager **internal CA** (`ok-shared-internal-ca`, self-signed bootstrap Issuer → CA → server cert), a **Vault-independent** origin — consistent with the bootstrap invariant (TLS trust for the Vault endpoint must not come from Vault itself). Not Let's Encrypt: `vault.ok-shared.internal` is not a public zone, so ACME/HTTP-01 cannot validate it.
- **Consumer-side obligations — name resolution is per consumer, not a blanket rule.** The single **invariant**: *traffic reaches the host-level LoadBalancer `192.168.100.207`, while TLS validation and SNI use `vault.ok-shared.internal`* — the SNI host, not just the IP, must match because passthrough routes on SNI. Two valid mechanisms; each consumer declares which it uses:
  - **provider-vault (ok-mgmt) — DNS / hostAliases variant:** `address: https://vault.ok-shared.internal:443`, with `hostAliases` (or CoreDNS) mapping `vault.ok-shared.internal → 192.168.100.207`.
  - **VSO (consumer cluster) — direct-IP variant:** `address: https://192.168.100.207:443` + `tlsServerName: vault.ok-shared.internal` (no hostname resolution asserted on the consumer).

  In both variants the internal CA bundle is wired into VSO via `VaultConnection.caCertSecretRef` (CA trust unchanged). Part of the ADR-025 profile — no separate ADR.
- **Path B (optional).** Native child-cluster LoadBalancer reachability via Multus/NAD (so `vault.ok-shared.internal` resolves to a **child-owned** LB IP) is an optional simplification tracked by **OK-57**, **not** an ADR-025 acceptance prerequisite.

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
- **Required test:** cut the Vault connection (scale the ok-shared `vault` StatefulSet to 0), verify the materialised consumer Secret is still served and existing observability workloads + a pod restart survive, then verify reconciliation (VSO resync + a rotation propagates) after Vault returns and is re-unsealed. Runbook + evidence capture: `platform/secrets/vault/runbooks/vault-outage-recovery.md` (with `conformance/outage-evidence.sh`); this is also the ADR-018 autonomy evidence.

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
- The singleton invariant is **enforced** by a Kubernetes-native **`ValidatingAdmissionPolicy`** on ok-mgmt that **pins the name** to `ok-shared-vault` (`platform/secrets/vault/crossplane/singleton-admission.yaml`): because `VaultInstance` is cluster-scoped, permitting only that one name bounds the population to **at most one** — a second production `VaultInstance` is rejected at admission (fail-closed, `validationActions: [Deny]`). No external policy controller is introduced, so no new platform capability (consistent with §Implementation & placement). A read-only **conformance** check and a non-mutating **negative test** (`platform/secrets/vault/conformance/`) supply the acceptance evidence; an internal XRD alone does not enforce a single instance.
- *Alternative:* an ok-shared bootstrap script — rejected (imperative, off the GitOps trajectory).

### Readiness — Helm-deployed ≠ Vault-ready (invariant)

`VaultInstance Ready=True` **MUST NOT** be derived from provider-helm's `Release=deployed` alone (Vault may be uninitialised, sealed, without Raft quorum / TLS / audit). Expose or gate distinct states: `Installed`, `Initialized`, `Unsealed`, `RaftHealthy`, `TLSReady`, `AuditEnabled`, `Configured`. If the first Composition can observe only the Helm state, it reports **only `Installed`**; a **separate deterministic health gate** supplies acceptance evidence — mirroring the observability contract-test-gate discipline. Realised as `platform/secrets/vault/gate/vault-health-gate.sh` (read-only; `Initialized` / `Unsealed` / `TLSReady` unauthenticated, `RaftHealthy` / `AuditEnabled` / `Configured` token-gated; exit non-zero on any FAIL), wrapped by `make health-gate`. `Configured` asserts only the dedicated per-cluster auth mount until the Day-1/Day-2 config reconciler is selected (item 13).

### Storage & failure domains

Vault uses **Integrated Storage (Raft)**. The `storageClass` in `VaultInstance` MUST be a StorageClass that exists **inside ok-shared**. The host-cluster `ok-storage` layer may protect the underlying KubeVirt VM disks, but it is **not** itself a workload-cluster StorageClass. The full durability chain MUST be declared and tested:

`Vault Raft replica → ok-shared PVC / node affinity → workload-node disk → KubeVirt VM disk → host ok-storage durability`

If the initial profile uses workload-cluster `local-path`, the ADR states its PVCs are node-affine and **not** independently replicated: Raft provides service-level replication, host storage protects the VM disk — neither silently substitutes the other.

Vault pods MUST be spread across distinct ok-shared nodes (anti-affinity). Replica count is bound to an explicit failure budget: **3 voters → quorum 2, tolerates 1 down; 5 voters → quorum 3, tolerates 2 down.** The chosen count + accepted budget are versioned production config, not chart defaults. Backups use **Vault Raft snapshots** stored outside the Vault cluster's own failure domain (PVC/VM snapshots alone are **not** the normative Vault backup); a restore rehearsal is required before acceptance. A one-off snapshot + successful restore proves the **restore mechanism**, not a backup **process**: before acceptance a **backup operating-model runbook** (manual is acceptable; CronJob / object-store automation is a Day-2 follow-up) MUST normatively fix **cadence, owner, external storage location, encryption + access control, retention, and a periodic restore test**. ADR-025 **MUST NOT** claim automated backups exist.

### Artifact placement

| Artifact | Home | Notes |
|---|---|---|
| `VaultInstance` XRD + Composition (provider-helm `Release`, versioned) | `openkubes` (platform) | internal singleton XR; reconciled from ok-mgmt onto ok-shared |
| **Non-secret production config** — HA/Raft, replicas, StorageClass (**inside ok-shared**; see Storage), volume sizes, TLS/ingress (`vault.ok-shared.internal`), seal type, audit storage, auth-mount names, policies, roles, network params | **versioned** in the `VaultInstance` XR / a tracked values doc in `openkubes` | committed & reviewable — **NOT** git-ignored provider values |
| **Offline custody material** — Shamir unseal/recovery shares + PGP-encrypted initial root token | offline origin independent of Vault **and** Kubernetes; **Phase 1: single-operator GPG custody — Accepted Risk AR-025-1** (rekey to distinct custodian PGP keys before multi-operator / external-production use) | root token is ceremony-only, revoked after evidenced use (`vault token revoke -self`) |
| **Operational bootstrap secrets** — TLS private key, token-reviewer credential, Transit token, HSM PIN/creds | Vault-independent secret origin/delivery; never Git, never dependent solely on this Vault | may come from an external PKI, cert-manager, Kubernetes, HSM/KMS — not necessarily offline human custody |
| VSO cluster add-on | pinned **ok-cluster** install target | explicit, versioned |
| Consumer `VaultStaticSecret` for `ok-observability-credentials` | **ok-cluster**, applied **before** observability helm | ADR-024/025; no chart change; = OK-109 Part 2 |
| Per-cluster auth: dedicated mount + roles + least-privilege policies + reviewer credential | **central declarative Vault reconciler**, triggered by cluster **registration** (ADR-013) | see "Vault configuration" |

### Lifecycle safeguards (production)

- The composed `Release` uses **`deletionPolicy: Orphan`**. **Deleting the XR MUST NOT uninstall Vault or delete its persistent data** — teardown is a separate, evidence-based decommission process.
- The XRD sets **`spec.defaultCompositionUpdatePolicy: Manual`**; the production XR is pinned to an explicitly promoted `CompositionRevision` (field layout per the deployed Crossplane version; Crossplane otherwise auto-adopts newer revisions).
- **Revision identity** includes: Composition revision, provider-helm version, Vault chart version, Vault image version/digest, versioned values, Vault-config revision (extends ADR-024's revision-identity invariant). The Vault-config reconciler `provider-vault` is pinned to **v4.0.1**; the managed-resource APIs in use are **`v1alpha1`** (cluster-scoped `*.vault.upbound.io`; the namespaced `*.m.upbound.io` variants are unused). API maturity is an **explicit revision characteristic**, not an assumed stability guarantee.

### Seal / unseal — bound to the recovery SLO

> **Phase-1 custody — Accepted Risk AR-025-1.** Vault uses five Shamir shares, threshold three. The shares are GPG-encrypted but are currently held under **single-operator custody** — recoverable without organisational **separation of duties**; OpenKubes explicitly accepts that concentration risk for Phase 1.
>
> **Hard gate — before multi-operator or external-production use.** Before use beyond the current single-operator environment (a second operator / on-call model, or external production workloads), Vault MUST be rekeyed to **distinct custodian PGP keys**, with share distribution + recovery rehearsed and evidence retained. (The full 5-custodian PGP ceremony is the production-hardening upgrade path.)
>
> **Root token — revoked (realised ceremony evidence, 2026-07-25).** The initial root token was used only to enable audit, admin auth and the automation seed, then revoked (`vault token revoke -self`, success recorded). **No standing root token exists.** Administrative break-glass is **`userpass/breakglass`** (a strong password under the same Phase-1 custody, delivered over **stdin only** — never argv/history/logs), and recovery uses the Shamir unseal ceremony — not a stored root token.

- **Phase-1 attended-production baseline: manual Shamir unseal, offline single-operator custody (Phase 1 — AR-025-1 above)** — OpenKubes **accepts a manual-recovery SLO for Phase 1** (attended re-unseal after restart; on 3-node Raft, every rescheduled pod → no unattended recovery after a full restart). Init with **PGP-encrypted shares + PGP-encrypted root token**; use the root token only to enable audit, admin auth and the automation identity, then **revoke it** (evidenced). Acceptance requires a **cold-restart rehearsal** recording achieved recovery time, confirming the unseal threshold can be met under the operating model, and that every required Raft voter returns to service.
- **Committed follow-up (not merely conditional):** unattended recovery **will** become a production requirement. When it does, Shamir is insufficient and auto-unseal from an **independently bootstrapped** origin is a blocking prerequisite: Transit (edition-neutral; adds a second Vault + renewable-token lifecycle; no Vault→Vault recursion) or PKCS#11/HSM (Vault Enterprise). The probable sovereign endpoint is HSM/Enterprise or a dedicated KMS/transit appliance.

### Vault configuration — one declarative reconciler, two phases

1. **Bootstrap ceremony** (once, supervised): init, unseal, audit device, initial admin auth, automation identity, root-token revocation. Runbook: `platform/secrets/vault/bootstrap/README.md` (PGP-encrypted Shamir shares + root token, each step bound to a health-gate state, includes the cold-restart rehearsal for items 4 & 12; seeds the config reconciler's single manual auth (Kubernetes auth for ok-mgmt + `ok-config-automation` policy, item 13)).
2. **Day-1/Day-2 reconciliation** (declarative): auth mounts, policies, roles, secret engines, per-registered-cluster config — through **exactly one** reconciler; production auth config MUST NOT be split across multiple authoritative reconcilers.

**Day-1/Day-2 Vault-config reconciler (decided — item 13):** exactly one authoritative mechanism = Crossplane `provider-vault` on **ok-mgmt**, driven by the same ADR-013 cluster-registration Composition (a `VaultConfig` XR per registered cluster renders auth mount + policies + roles as Vault managed resources). Chosen for continuous drift correction, reuse of the running control plane and registration trigger, and the absence of a sensitive external state file; a single reconcile loop precludes split-brain over auth config. Terraform (vault provider) was rejected for its drift-only-on-`plan` model and a sensitive state file off the Crossplane/GitOps trajectory; a config Job was rejected as drift-blind/imperative.

**Automation identity & bounded recursion:** the reconciler authenticates via Vault **Kubernetes auth for ok-mgmt** with the least-privilege `ok-config-automation` policy and short-lived tokens (no standing credential). Its own auth mount + policy binding are the **single manual seed** created during the bootstrap ceremony (Vault-independent origin = the ceremony root token), preserving the bootstrap-without-recursion invariant; all further Vault config is reconciled declaratively. Provider version is **pinned** and resource coverage (kubernetes auth backend + role, policy, mount) confirmed as part of this record.

**Least-privilege scope (normative — criterion 13).** The `ok-config-automation` policy MUST be confined to **reserved prefixes**: it may address only reconciler-owned ACL policies (`sys/policies/acl/okvc-*`) and the OpenKubes Kubernetes-auth namespace (`sys/auth/kubernetes/*`, `auth/kubernetes/*`), plus `auth/token/create` for the Upjet child token, with an explicit **deny** on the lifecycle of its own manually seeded mount (`sys/auth/kubernetes/ok-mgmt`, `auth/kubernetes/ok-mgmt`, and their sub-paths). Deny wins in Vault, so the automation **cannot disable, tune, or re-role its own seed mount** (preserving the bootstrap / non-recursion invariant). Global policy listing (`LIST /sys/policies/acl`) is granted **only** if the provider is proven to need it. If `provider-vault`'s API usage genuinely cannot be confined to these prefixes, the ADR **MUST NOT** claim "least privilege"; the accurate wording is then **"bounded Vault configuration administrator for the declared OpenKubes auth and policy scope"**, with the residual blast radius recorded as an Accepted Risk.

**Reserved name scheme (normative).** Reconciler-managed policies are prefixed **`okvc-`** (the Composition renames `<cluster>-<role>` → `okvc-<cluster>-<role>`, including the `AuthBackendRole` `tokenPolicies`). **Mount-namespace reservation:** all `auth/kubernetes/<ADR-013-cluster-id>` mounts are reconciler-owned, **except** the manually seeded and explicitly protected `auth/kubernetes/ok-mgmt`; no unrelated or manually managed auth method may use this path namespace. If a non-reconciler Kubernetes mount is ever needed there, migrate naming to `kubernetes/okvc-<cluster-id>` or re-narrow the policy. Ownership of the reconciler-managed policy was migrated to this `okvc-` identity and the narrowing proven live — evidence in `ADR-Platform-025-A6-ownership-migration-acceptance-record.md`.

### Decisions requiring ownership

1. **Recovery class** — *decided:* attended Shamir (offline custody) for Phase 1; unattended auto-unseal is a committed follow-up.
2. **Failure budget** — *open (acceptance-gated):* 3 voters (tolerate 1) vs 5 voters (tolerate 2). A 3-node controlled pilot is defensible **as an accepted risk**, not an implicit chart default.
3. **Declarative reconciler** — *decided:* Crossplane `provider-vault` on ok-mgmt, ADR-013-triggered, K8s-auth automation identity seeded by the bootstrap ceremony (see above). Remaining is *implementation* (the `VaultConfig` XR + provider version pin), not selection.

The `VaultInstance` XRD/Composition scaffold may begin now provided it does not silently choose defaults for the open items; production VSO onboarding follows the reconciler *implementation* (the selection is now made).

## Acceptance evidence — realised (2026-07-26)

Proven items referenced *in* the ADR for visibility (the full 15-point acceptance-evidence matrix lives in the **OK-110 review thread**, not here — to avoid a second normative truth next to the ADR):

- **Bootstrap ceremony:** init 5/3 Shamir; audit device enabled; **root token revoked**; break-glass `userpass/breakglass`. Cold-restart rehearsal: **89s**, `voters=3/3`, threshold met.
- **Category-A reviewer model:** dedicated SA `vault-reviewer` + `system:auth-delegator`; Vault mount `auth/kubernetes/<cluster>` configured with `token_reviewer_jwt` (not just a successful TokenReview).
- **Migration without credential change:** existing `ok-observability-credentials` taken over by VSO (`overwrite`), **identical values, zero workload restarts**, OK-79 contract gate green.
- **Rotation (rotatable credential):** `secret/ok-robotics/obs/rotation-demo` key `token`, **`v1-alpha → v2-bravo`** → VSO refresh → `rolloutRestartTargets` → consumer read new value. (Explicitly **not** the OpenSearch bootstrap password.)
- **Reachability:** Path A, MetalLB on **ok-infra** (see §Cross-cluster reachability).
- **Backup/restore:** **manual** external Raft snapshot + **restore rehearsal** (rollback proven). Record the snapshot **location, SHA-256, restore-run outcome, and retention/deletion** to fully satisfy criterion 11. **Scheduled off-host backup (CronJob / object store) remains a Day-2 follow-up — no claim that automated backups exist.**
- **A6 ownership migration (criterion 13 closed):** reconciler-managed policy migrated to the reserved `okvc-` identity and `ok-config-automation` narrowed to least privilege — full record in `ADR-Platform-025-A6-ownership-migration-acceptance-record.md`.

## Path to acceptance (evidence required before `Accepted`)

1. **Mandatory reconciliation settings** defined and tested: `refreshAfter` is always configured; Enterprise `instantUpdates`, if enabled, remains an optional latency optimization, not a conformance dependency. (Edition itself is a deployment/ops choice, not an acceptance gate.)
2. **Auth mount per cluster** + workload-scoped roles/policies implemented.
3. **Authentication topology applied per cluster.** For each onboarded cluster, evidence is required only for its **selected** authentication category; categories not currently instantiated remain **activation-gated profiles, not acceptance dependencies** (Category A proven on ok-robotics; B and C gated until such a cluster exists). Per-category requirements when instantiated:
   - **Category A:** Vault→TokenReview reachability proven, and the reviewer-credential model documented and tested without granting unintended cluster-wide privilege.
   - **Category B:** OIDC discovery or JWKS reachable; for a mirrored JWKS, publication freshness and old/new-key overlap tested.
   - **Category C:** activated only with the key-overlap procedure, short-lived projected tokens, synthetic auth-failure detection, and CR-status / audit-log alerting in place.
4. **Unseal / HA / backup / restore** strategy set, and **restore tested**.
5. Vault bootstrap works **without Vault/VSO recursion** (invariant above).
6. An **existing** observability install migrated **without credential change**.
7. A **fresh** install receives the Secret **before** the Helm release.
8. **Vault outage + reconciliation** tested per `runbooks/vault-outage-recovery.md`: full outage via `vault` StatefulSet scale-to-0 — consumer Secret still served + unchanged, workloads + a pod restart survive; after scale-up + attended re-unseal, VSO resyncs and a rotation propagates. Evidence captured in `ADR-Platform-025-crit8-outage-recovery-acceptance-record.md` (also closes the ADR-018 autonomy outage evidence).
9. **Rotation** proven with an actually-rotatable consumer (not the OpenSearch bootstrap password).
10. ADR-024 / OK-109 Contract Gate re-runs **green** with the materialised Secret.
11. **Failure budget decided** (3 vs 5 voters, accepted risk) + pod anti-affinity across ok-shared nodes; **Vault Raft snapshot** backup outside the cluster's failure domain, with a **restore rehearsal** completed, and a **backup operating-model runbook** fixing cadence, owner, external storage location, encryption + access control, retention, and a periodic restore test (manual acceptable; scheduled off-host automation is a Day-2 follow-up — no claim of automated backups).
12. **Cold-restart rehearsal** recorded: recovery time, unseal threshold met under the operating model, all required Raft voters returned to service.
13. **Day-1/Day-2 Vault-config reconciler** — *selected, narrowed & closed (A6):* Crossplane `provider-vault` **v4.0.1** on ok-mgmt (see §Vault configuration); `VaultConfig` XR implemented, `ok-config-automation` narrowed to reserved prefixes with **deny** on its own seed mount and proven live (negative test passed), ownership migrated to the reserved `okvc-` identity, break-glass rotated and its tokens revoked. Evidence: `ADR-Platform-025-A6-ownership-migration-acceptance-record.md`.
14. **Singleton invariant enforced** — a `ValidatingAdmissionPolicy` on ok-mgmt name-pins `VaultInstance` to `ok-shared-vault` (cluster-scoped ⇒ at most one), fail-closed with `validationActions: [Deny]` (`crossplane/singleton-admission.yaml`). Evidence: `make singleton-conformance` green and `make singleton-negative-test` proving a second `VaultInstance` is rejected at admission (`conformance/`), captured in `ADR-Platform-025-crit14-singleton-enforcement-acceptance-record.md`.
15. **Non-manual cross-cluster reachability** proven via **Path A**: consumer reaches Vault over the stable host-cluster LoadBalancer (`192.168.100.207:443`, MetalLB on **ok-infra**) → ok-shared Traefik `IngressRouteTCP` (TLS passthrough, `HostSNI(vault.ok-shared.internal)`, `vault-active` backend), cert-manager server TLS, consumer-side CA trust (name resolution per consumer — DNS/hostAliases or direct-IP + `tlsServerName`) — replacing the PoC's manual host-cluster LB proxy. Path B (native child LB, OK-57) is optional, not a gate.

## Re-evaluation triggers

- A second datacenter secret backend becomes required → revisit the single-provider trade-off.
- The edge profile needs central visibility → separate ADR (does not change this one).
