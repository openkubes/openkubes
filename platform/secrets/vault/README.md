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
- Run the **bootstrap ceremony** (init/unseal, custody, root-token revoke) —
  supervised, out of band. Runbook: `bootstrap/README.md`.
- Backup/restore: Raft snapshot outside the failure domain + restore rehearsal.
- **Verify the TLS render** — server TLS is wired in the composition
  (`global.tlsDisable: false`, `vault-server-tls` mounted, https Raft
  `retry_join`, TLS-aware health probe via `VAULT_ADDR`/`VAULT_CACERT`). Run
  `helm template` against pinned chart `0.30.1` before apply; the `retry_join`
  peer list is coupled to `replicas: 3` and must track any failure-budget change.

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

## Day-1/2 config reconciler (ADR-025 item 13)

Vault *configuration* (auth mounts, policies, roles) is reconciled by **Crossplane
`provider-vault` on ok-mgmt** — one authoritative loop, continuous drift
correction, no external state file. Driven by the ADR-013 registration
Composition: one `VaultConfig` XR per consuming cluster renders that cluster's
dedicated `auth/kubernetes/<cluster>` mount + workload-scoped least-privilege
roles/policies as provider-vault managed resources.

```
crossplane/provider-vault.yaml         Provider (PINNED) + ProviderConfig (K8s-auth, ceremony-seeded)
crossplane/vaultconfig-xrd.yaml        VaultConfig XRD (internal, per-cluster, Manual)
crossplane/vaultconfig-composition.yaml provider-vault MRs (go-templating loop over roles)
crossplane/examples/ok-robotics-vaultconfig.yaml   Category-A example (sa-obs)
```

**Not applyable yet — TO-VERIFY:** pin the tested `provider-vault` version and
confirm MR CRD coverage (`kubectl get crds | grep vault`); the MR
`apiVersion`s/field names in the Composition are the expected Upjet shape and
must be checked against the installed provider. Sensitive inputs (reviewer JWT,
CA) are secret-ref only, never inline (ADR-024 hygiene). The reconciler's own
auth is the single manual seed from the bootstrap ceremony (Step 3c).

## Health gate (readiness ≠ installed)

The XR's `Ready` only proves the Helm release is INSTALLED. Operational readiness
is asserted by a **separate deterministic runtime gate** that supplies acceptance
evidence (ADR-025), mirroring the observability contract-test-gate discipline:

```
gate/vault-health-gate.sh   Initialized / Unsealed / RaftHealthy / TLSReady /
                            AuditEnabled / Configured — read-only, exit 1 on any FAIL
Makefile                    `make validate` (scaffold safety invariants),
                            `make health-gate` (runtime gate wrapper)
```

Unauthenticated checks (Initialized, Unsealed, TLSReady) run without a token;
RaftHealthy / AuditEnabled / Configured need `VAULT_TOKEN` (else SKIP, or FAIL
with `--require-auth`). `Configured` only asserts the dedicated per-cluster k8s
auth mount — policies/roles depend on the still-open Day-1/2 config reconciler
(ADR-025 item 13).

```bash
VAULT_ADDR=https://vault.ok-shared.internal:443 VAULT_CACERT=./ok-shared-ca.crt \
VAULT_EXPECT_REPLICAS=3 VAULT_TOKEN=… VAULT_EXPECT_AUTH_MOUNTS=ok-robotics \
make health-gate            # or: bash gate/vault-health-gate.sh --require-auth
```

## Layout

```
Makefile                            local validate + health-gate wrapper
crossplane/xrd.yaml                 VaultInstance XRD (singleton, Manual updates)
crossplane/composition.yaml         provider-helm Release (Raft, Orphan, pinned, TLS)
crossplane/examples/ok-shared-vault.yaml   the singleton XR (placeholder values)
crossplane/reachability.yaml        internal CA + server cert + IngressRouteTCP (passthrough)
gate/vault-health-gate.sh           deterministic runtime health gate
bootstrap/README.md                 supervised init/unseal ceremony runbook
```
