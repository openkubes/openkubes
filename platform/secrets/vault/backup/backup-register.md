# Vault backup register (ADR-025 crit. 11 / A10)

Append-only log of Vault Raft snapshots. Written by
`platform/secrets/vault/backup/vault-raft-snapshot.sh`. Contains **no secret
material** — only file names, sizes, SHA-256 integrity hashes, the custodian
recipient id, off-host destination, and retention. Restore rehearsals flip the
last column to the rehearsal date. See `runbooks/vault-backup-operating-model.md`.

| Timestamp (UTC) | File | Size (B) | SHA-256 (plaintext) | SHA-256 (encrypted) | Recipient | Off-host | Retain until | Restore-tested |
|---|---|---|---|---|---|---|---|---|
| 20260726T194344Z | vault-20260726T194344Z.snap.gpg | 78305 | 37a9d4b1ea1b0dbfe912d76e14cf51f2d65d359c96d6668d51cf0124c5aa98da | d755e9903a51655ff29c41fa8b36e1f2da704c6ba33ac7e097768b4c229bfc73 | D0204299FC0840FC0EDBB83ACEF6803E5BB0FE01 | /Users/arash/vault-backups/vault-20260726T194344Z.snap.gpg | 2026-08-09 | no |
