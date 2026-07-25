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
- **Enable Vault server TLS** (listener `tls_cert_file`, mount `vault-server-tls`,
  https Raft `retry_join`) — the composition change that makes passthrough live.

## Cross-cluster reachability (ADR-025, OK-110)

Consumers reach the central Vault via the **ok-shared Traefik ingress** as an
`IngressRouteTCP` with **TLS passthrough** and `HostSNI(vault.ok-shared.internal)`,
backed by the leader-only `vault-active` service. This replaces the manual
host-cluster LB proxy from the PoC and makes OK-57 an optional simplification,
not a prerequisite. See `crossplane/reachability.yaml`.

- **Passthrough (not termination):** Vault is a secret backend — TLS is
  end-to-end, no plaintext hop in ok-shared, audit sees the real client.
- **`vault-active` backend:** routing to the plain `vault` service can hit a
  Raft standby, which 307-redirects to the leader's internal `api_addr` — a
  cross-cluster consumer cannot follow that. `vault-active` is leader-only.
- **Server TLS** is issued by cert-manager's internal CA (`ok-shared-internal-ca`)
  — a Vault-independent trust origin, satisfying the bootstrap invariant.

### Consumer runbook (each datacenter consumer cluster, e.g. ok-robotics)

1. **DNS** — `vault.ok-shared.internal` is not a public zone. Add a CoreDNS
   entry resolving it to the ok-shared ingress MetalLB IP (the SNI host, not
   just the IP, must match — passthrough routes on SNI):

   ```
   # CoreDNS Corefile (hosts plugin) on the consumer cluster
   hosts {
       <OK_SHARED_INGRESS_MetalLB_IP>  vault.ok-shared.internal
       fallthrough
   }
   ```

2. **CA trust** — export the internal CA and give VSO the bundle:

   ```
   kubectl -n vault get secret ok-shared-internal-ca \
     -o jsonpath='{.data.tls\.crt}' | base64 -d > ok-shared-ca.crt
   # on the consumer cluster:
   kubectl -n <vso-ns> create secret generic vault-ca --from-file=ca.crt=ok-shared-ca.crt
   ```

   ```yaml
   # VaultConnection on the consumer cluster
   spec:
     address: https://vault.ok-shared.internal:443
     tlsServerName: vault.ok-shared.internal
     caCertSecretRef: vault-ca
   ```

## Layout

```
crossplane/xrd.yaml                 VaultInstance XRD (singleton, Manual updates)
crossplane/composition.yaml         provider-helm Release (Raft, Orphan, pinned)
crossplane/examples/ok-shared-vault.yaml   the singleton XR (placeholder values)
crossplane/reachability.yaml        internal CA + server cert + IngressRouteTCP (passthrough)
```
