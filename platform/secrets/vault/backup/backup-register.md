# Vault backup register (ADR-025 crit. 11 / A10)

Append-only log of Vault Raft snapshots. Written by
`platform/secrets/vault/backup/vault-raft-snapshot.sh`. Contains **no secret
material** — only file names, sizes, SHA-256 integrity hashes, the custodian
recipient id, off-host destination, and retention. Restore rehearsals flip the
last column to the rehearsal date. See `runbooks/vault-backup-operating-model.md`.

| Timestamp (UTC) | File | Size (B) | SHA-256 (plaintext) | SHA-256 (encrypted) | Recipient | Off-host | Retain until | Restore-tested |
|---|---|---|---|---|---|---|---|---|
| 20260726T194344Z | vault-20260726T194344Z.snap.gpg | 78305 | 37a9d4b1ea1b0dbfe912d76e14cf51f2d65d359c96d6668d51cf0124c5aa98da | d755e9903a51655ff29c41fa8b36e1f2da704c6ba33ac7e097768b4c229bfc73 | D0204299FC0840FC0EDBB83ACEF6803E5BB0FE01 | /Users/arash/vault-backups/vault-20260726T194344Z.snap.gpg | 2026-08-09 | superseded/deleted — re-keyed (OK-113) |
| 20260726T200603Z | vault-20260726T200603Z.snap.gpg | 75416 | 952a95148b14da7c1309b935a1e17e914a73121e9492264c975f31fd6883ceca | 622462fc8c1f9b3d28745133c53abc4d04bde1e7577471a6bfa025ed510fa8c8 | 0E3AF6C9CA71C96E23892AB45D3F5BFDAE1DF20F | /Users/arash/vault-backups/vault-20260726T200603Z.snap.gpg | 2026-08-02 | 2026-07-26 mechanism verified (FSM install; full-unseal DR pending OK-113) |
| 20260727T080155Z | vault-20260727T080155Z.snap.gpg | 76877 | 7e49090c63925a0794ecebc24ae13ba8286e7b451f7c3727ab5324db56cfa19c | 39091d129c2f28a0c401ab60e8c00728bc713591d444686faba56f51b2657608 | 0E3AF6C9CA71C96E23892AB45D3F5BFDAE1DF20F | /Users/arash/vault-backups/vault-20260727T080155Z.snap.gpg | 2026-08-03 | no |
