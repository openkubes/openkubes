# Vault backup register (ADR-025 crit. 11 / A10)

Append-only log of Vault Raft snapshots. Written by
`platform/secrets/vault/backup/vault-raft-snapshot.sh`. Contains **no secret
material** — only file names, sizes, SHA-256 integrity hashes, the custodian
recipient id, off-host destination, and retention. Restore rehearsals flip the
last column to the rehearsal date. See `runbooks/vault-backup-operating-model.md`.

| Timestamp (UTC) | File | Size (B) | SHA-256 (plaintext) | SHA-256 (encrypted) | Recipient | Off-host | Retain until | Restore-tested |
|---|---|---|---|---|---|---|---|---|
