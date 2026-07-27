# Vault auto-unseal via Transit — design + rollout (OK-114)

**Goal.** ok-shared Vault auto-unseals on restart via a **Transit** engine in a small, independent
Transit Vault — no attended Shamir unseal, no memorized passphrase in the critical recovery path
(the OK-113 failure mode). Sovereign, edition-neutral.

## Architecture

```
 ┌──────────────┐  seal "transit" (encrypt/decrypt master key)  ┌───────────────────┐
 │ ok-shared    │ ────────────────────────────────────────────▶ │ Transit Vault     │
 │ Vault (3-node│   scoped token: transit/{en,de}crypt/          │ (independent,     │
 │ raft)        │   autounseal-ok-shared                         │  own Shamir seal) │
 └──────────────┘                                                └───────────────────┘
```

- The Transit Vault is **independent of ok-shared** (bootstrap invariant). It is only needed **at
  unseal time** — a running ok-shared does not depend on it continuously.
- After migration, ok-shared's **old Shamir unseal keys become RECOVERY keys** (Recovery Seal Type
  shamir). Keep that custody (verified) — recovery keys are still needed for generate-root / rekey /
  future seal-migration.
- **crit. 14 interaction:** the Transit Vault must NOT be a second `VaultInstance` XR (the singleton
  admission policy name-pins `ok-shared-vault`). Deploy it as a standalone Helm release / manifests.

## Lab validation (2026-07-27) — PROVEN end-to-end (local Docker rig, zero cluster risk)

Two containers on a Docker network (`transit-vault`, `shadow-vault`/`shadow-mig`), file/raft
storage, tls_disable (localhost only). Both scenarios green:

1. **Greenfield auto-unseal:** shadow-vault with `seal "transit"` → `init -recovery-shares` →
   auto-unsealed on init → **restart → `Sealed false` with no unseal command**.
2. **Shamir → transit migration (single node):** Shamir vault with data →
   append `seal "transit"` stanza → restart (`Seal Migration in Progress: true`, sealed) →
   `vault operator unseal -migrate <shamir-key>` → `Seal Type transit`, unsealed →
   **restart → `Sealed false` (auto); canary secret survived.**
3. **Shamir → transit migration, 3-node RAFT HA (the exact prod choreography):** each node,
   restarted with the seal stanza, comes up `Seal Migration in Progress`; each is unsealed with
   `vault operator unseal -migrate <shamir-key>` — **standbys first, the active node last**. After
   all three: full restart of all nodes **auto-unseals with no `-migrate`**, 3 voters + leader,
   canary survived. The old Shamir shares become **recovery keys**.

Transit provider setup (proven):
```bash
vault secrets enable transit
vault write -f transit/keys/autounseal-ok-shared
vault policy write autounseal - <<'HCL'
path "transit/encrypt/autounseal-ok-shared" { capabilities = ["update"] }
path "transit/decrypt/autounseal-ok-shared" { capabilities = ["update"] }
HCL
vault token create -policy=autounseal -period=24h -orphan -field=token   # -> seal token
```

seal stanza (proven):
```hcl
seal "transit" {
  address    = "http://transit-vault:8200"   # prod: https://<transit-endpoint>
  token      = "<autounseal-token>"           # prod: inject via Secret/env, never committed
  key_name   = "autounseal-ok-shared"
  mount_path = "transit/"
}
```

## Prod rollout plan (ok-shared) — EXECUTED 2026-07-27 ✓

> **Outcome — SUCCESS.** Transit Vault deployed on ok-mgmt (verified 3/2 Shamir custody), exposed
> on the SDN at 192.168.100.208 via an ok-infra LoadBalancer. The `seal "transit"` stanza was
> promoted into the ok-shared composition (token via `env://` from Secret `vault-transit-seal`, CA
> mounted). Shamir→transit migration ran in the lab-verified HA order (standbys vault-2/vault-1
> first, active vault-0 last, `unseal -migrate` × 3 recovery keys each). Migration completed
> cluster-wide; a full 3-pod restart **auto-unsealed with no manual step**; VSO/consumer Secret on
> ok-robotics stayed `Synced/Healthy`. Old Shamir shares are now the **recovery keys**. Follow-ups:
> back up the Transit Vault data + verified custody; monitor/rotate the scoped seal token.

**Constraint:** do not install anything on the mother RKE2 (ok-infra). Transit Vault host = ok-mgmt
(a Talos guest cluster — safe to extend), decided OK-114.

1. **Transit Vault on ok-mgmt** (standalone Helm release, single node):
   - **Storage:** ok-mgmt has no StorageClass → install `local-path-provisioner` on ok-mgmt (guest
     cluster; does not touch ok-infra) for a durable PVC. The Transit Vault's data (the transit
     key) is **critical** — it must persist and be backed up.
   - **Own seal:** Shamir with **decrypt-verified** custody (small blast radius, rarely restarts).
   - **TLS:** issue a server cert (cert-manager if present, else a self-signed internal CA). The
     seal token is powerful — do **not** run the transit endpoint plaintext across the SDN in prod.
   - **Reachability:** ok-shared pods (10.35.x) reach ok-mgmt only over the **SDN 192.168.100.x**
     (per-cluster overlays are not cross-routable). Expose Transit via a stable 192.168.100.x
     endpoint (NodePort on the ok-mgmt SDN node IPs, or the host-LB pattern). Confirm the ok-mgmt
     nodes' SDN addresses first.
2. **Transit engine + key + scoped token** (as in the lab).
3. **seal "transit" on ok-shared** via the `VaultInstance` composition values (`server` raft config
   HCL). **Inject the token via a Kubernetes Secret / `VAULT_SEAL_TRANSIT_TOKEN` env**, not the
   committed composition. Promote the CompositionRevision (Manual policy).
4. **Migration (lab-verified HA choreography).** The ok-shared StatefulSet is `OnDelete`, so
   promoting the composition updates the ConfigMap/STS **without** restarting pods — the migration
   is fully controlled:
   - Find the leader: `vault operator raft list-peers` (the `leader`).
   - **Standbys first, one at a time:** `kubectl -n vault delete pod vault-<standby>` → it returns
     `Seal Migration in Progress` (sealed) → `kubectl -n vault exec -i vault-<standby> -- vault
     operator unseal -migrate` × threshold with the **current verified Shamir keys** → `Sealed
     false`. Repeat for the second standby.
   - **Active node last:** delete the leader pod → migrate-unseal it the same way.
   - **Proof:** delete all three pods → they **auto-unseal via transit, no `-migrate`**; VSO/consumer
     Secret unaffected. The old Shamir shares are now **recovery keys** (keep the verified custody).
5. **Cold-restart rehearsal (ADR-025 item 12)** re-run under auto-unseal: delete all ok-shared vault
   pods → they return `Sealed false` unattended, `voters=3/3`.
6. **Transit Vault backup + custody** documented; recovery drill for "Transit Vault lost" (restore
   Transit from its own backup → ok-shared can unseal again).

## Open prod decisions (before rollout)

- Confirm ok-mgmt node SDN IPs + the Transit endpoint (NodePort vs host-LB).
- TLS approach on ok-mgmt (cert-manager vs self-signed internal CA).
- Token injection mechanism into the ok-shared pods (Secret + env).
- Transit Vault HA? (single node acceptable for Phase 1 — only needed at unseal time; document the
  "transit down → ok-shared can't restart until transit back" tolerance.)

## Lab teardown

```bash
docker rm -f shadow-vault shadow-mig transit-vault
docker network rm vault-shadow
rm -rf ~/vault-shadow
```
