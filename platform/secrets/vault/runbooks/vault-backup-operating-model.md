# Vault backup operating model — ADR-Platform-025 crit. 11 (amendment A10)

**Why this exists.** A one-off Raft snapshot + a successful restore rehearsal proves the *restore
mechanism*, not a backup **process**. ADR-025 (A10) requires a normative operating model before
acceptance and states **the ADR must NOT claim automated backups exist** — Phase-1 is a
**manual, scheduled** runbook; a CronJob / object-store pipeline is a Day-2 follow-up.

This runbook fixes the six required parameters: **cadence, owner, external storage location,
encryption + access control, retention, and a periodic restore test.**

---

## Operating parameters (DECIDE → confirm in three-way review)

Recommended defaults are proposed; the `DECIDE` values are org-policy choices — confirm, don't
silently accept.

| Parameter | Recommended default | Decision |
|---|---|---|
| **Cadence** | **daily** manual `vault operator raft snapshot save`, plus **ad-hoc before any Vault change** (upgrade, unseal-key rekey, composition promotion) | DECIDE |
| **Owner** | the Vault custodian (Phase-1: **Arash**, single-operator per AR-025-1); backup is part of the custodian role | DECIDE |
| **External storage** | off the ok-shared failure domain — **off-host** on `ok-infra` (encrypted dir) **and** a second copy off-cluster (removable/offsite). NOT a PVC/VM snapshot on the same host | DECIDE (path) |
| **Encryption + access control** | snapshot **GPG-encrypted to the custodian key at rest** (same custody as the unseal shares); plaintext `.snap` never leaves a tmpfs/working dir; filesystem perms `0600`, dir `0700` | DECIDE (recipient key) |
| **Retention** | keep **daily for 14 days**, **weekly for 8 weeks**; prune older; never keep plaintext | DECIDE |
| **Restore test** | **quarterly** restore rehearsal into a **throwaway** Vault (never production); record outcome | DECIDE (cadence) |

> These are **not** the Vault non-secret production config (that lives versioned in the XR). This
> is an operational runbook; the chosen values are recorded here + in the OK-110 thread.

## What a Vault backup is (and is not)

- **Is:** an integrated-storage **Raft snapshot** (`vault operator raft snapshot save`) — a
  consistent point-in-time of Vault's entire logical state, restorable onto a fresh Vault.
- **Is not:** a PVC/VM disk snapshot. Those protect the VM disk but are **not** the normative
  Vault backup (no application-consistent guarantee, tied to the same failure domain).
- The snapshot is **sensitive** (contains all secret material, encrypted with the Vault
  data/seal keys) — it MUST be encrypted at rest and access-controlled like the unseal shares.

## Taking a backup (manual, Phase-1)

Helper: `platform/secrets/vault/backup/vault-raft-snapshot.sh` — snapshots via `vault-0`, copies
out, hashes, GPG-encrypts, optionally copies off-host, and appends a row to the backup register.

```bash
export VAULT_CONTEXT=ok-shared VAULT_NS=vault
export GPG_RECIPIENT=<custodian-key-id>            # same custody as the unseal shares
export OFFHOST_DIR=/srv/vault-backups              # on ok-infra (or a mounted offsite target)
export VAULT_TOKEN=<break-glass token, via stdin/env — never argv/history>
make -C platform/secrets/vault raft-snapshot
```

The helper records, per backup: **UTC timestamp, file, size, SHA-256 (plaintext + encrypted),
recipient, off-host destination, retention-until** into `backup/backup-register.md`. Verify the
row landed and the encrypted artifact exists off-host before considering the backup done.

Manual equivalent (if not using the helper):

```bash
kubectl --context "$VAULT_CONTEXT" -n "$VAULT_NS" exec -i vault-0 -- \
  env VAULT_TOKEN="$VAULT_TOKEN" vault operator raft snapshot save /tmp/vault.snap
kubectl --context "$VAULT_CONTEXT" -n "$VAULT_NS" cp vault-0:/tmp/vault.snap ./vault-$(date -u +%Y%m%dT%H%M%SZ).snap
kubectl --context "$VAULT_CONTEXT" -n "$VAULT_NS" exec vault-0 -- rm -f /tmp/vault.snap
sha256sum ./vault-*.snap
gpg --encrypt --recipient "$GPG_RECIPIENT" ./vault-*.snap && shred -u ./vault-*.snap   # keep only the .gpg
```

## Restore rehearsal (quarterly, into a THROWAWAY Vault)

**Never restore into production as a test.** Restore replaces all state.

1. Stand up a scratch single-node Vault (dev/ephemeral, or a temporary VaultInstance in a
   sandbox namespace — note the singleton policy pins the *production* name, use a different
   cluster/namespace out of scope of the ok-mgmt policy).
2. Decrypt the latest snapshot to a tmpfs, `vault operator raft snapshot restore`, unseal.
3. Assert a known key reads back (e.g. `secret/ok-robotics/obs/...` present), then **destroy the
   scratch Vault**.
4. Record the rehearsal outcome + date in the register / acceptance record. `shred` the plaintext.

The most recent production restore rehearsal (rollback proven) is recorded in the OK-110 A7
evidence; this runbook makes it a **recurring** obligation.

## Integrity & recovery-readiness checks

- Every snapshot's SHA-256 is recorded at creation and re-verified before any restore.
- A backup is only "good" once (a) encrypted, (b) copied **off** the ok-shared failure domain,
  and (c) registered. A snapshot still sitting in the pod or on a single host is **not** a backup.
- Recovery readiness depends on BOTH the snapshot **and** the unseal shares (AR-025-1 custody) —
  keep them recoverable together but access-controlled.

## Day-2 follow-up (explicitly NOT claimed today)

- Scheduled off-host backup via CronJob (`vault operator raft snapshot save` → object store) with
  server-side encryption, lifecycle/retention, and monitored success — tracked separately. Until
  it exists and is evidenced, **do not claim automated backups**.

## Sign-off

- Confirm the DECIDE values (cadence, owner, off-host path, recipient key, retention, restore
  cadence) in the three-way review; record them in the OK-110 thread.
- This runbook + the first registered backup + a restore rehearsal close ADR-025 criterion 11's
  operating-model requirement.
