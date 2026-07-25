# Vault — datacenter secret backend (SCAFFOLD)

Crossplane XRD + Composition standing up the production Vault singleton on
`ok-shared`, implementing the datacenter secret-sync profile of
**ADR-Platform-025** (and the Secret Contract, ADR-Platform-011 / OK-71).
Related: OK-110 (production Vault standup), OK-109 (VSO rewiring, last).

**Status: scaffold / draft — not production-applyable.** It stands up the Vault
*server* only. It does not initialise, unseal, configure, or wire secrets.

## Design (from ADR-025)

- **Internal singleton XR** — `VaultInstance` has **no `claimNames`**. Vault is a
  bounded singleton implementation profile, not a self-service capability.
- **Manual revision promotion** — `defaultCompositionUpdatePolicy: Manual`; the
  chart version is pinned in the Composition (revision identity).
- **Stateful safety** — composed Helm `Release` uses `deletionPolicy: Orphan`;
  deleting the XR never uninstalls Vault or deletes its Raft data.
- **Readiness ≠ installed** — the XR's `Ready` reflects the Helm release state
  (INSTALLED) only. Operational readiness (Initialized / Unsealed / RaftHealthy
  / TLSReady / AuditEnabled / Configured) is asserted by a **separate health
  gate**, which supplies acceptance evidence.
- **Storage** — `dataStorageClass` is required with no default and MUST be a
  StorageClass that exists **inside** the target cluster (not host `ok-storage`).
- **Failure domains** — Raft integrated storage, pod anti-affinity across nodes.
- **Seal** — Phase-1 attended Shamir/offline (accepted manual-recovery SLO);
  unattended auto-unseal (Transit/HSM) is a committed follow-up.

## Open, acceptance-gated decisions (ADR-025) — must not be silently defaulted

1. **Failure budget** — `replicas` 3 (tolerate 1) vs 5 (tolerate 2). No default;
   the example uses `3` as a placeholder to confirm.
2. **Day-1/2 config reconciler** — exactly one declarative reconciler for Vault
   config (auth methods, policies, mounts). Not part of this scaffold.

## TODO before production

- Enforce the singleton invariant (admission/conformance check).
- Confirm the pinned chart version and the real ok-shared StorageClass.
- Add the separate Vault health/conformance gate.
- Bootstrap ceremony (init/unseal, custody) — supervised, out of band.

## Layout

```
crossplane/xrd.yaml                 VaultInstance XRD (singleton, Manual updates)
crossplane/composition.yaml         provider-helm Release (Raft, Orphan, pinned)
crossplane/examples/ok-shared-vault.yaml   the singleton XR (placeholder values)
```
