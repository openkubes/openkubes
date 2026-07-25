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

## Re-evaluation triggers

- A second datacenter secret backend becomes required → revisit the single-provider trade-off.
- The edge profile needs central visibility → separate ADR (does not change this one).
