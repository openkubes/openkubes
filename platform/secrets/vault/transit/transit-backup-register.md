# Transit Vault backup register (OK-114)

Encrypted `file`-storage snapshots of the Transit Vault (auto-unseal provider).
No secret material in this file — hashes + paths only. Recovery also needs
the Transit Shamir shares (~/transit-init.json.gpg).

| Timestamp (UTC) | File | Size (B) | SHA-256 (encrypted) | Recipient |
|---|---|---|---|---|
| 20260727T100620Z | transit-data-20260727T100620Z.tar.gz.gpg | 17218 | fa587797a2d8e71269df8d34a57020099c677d5f8246de1ed563a5d2a7da92e4 | 0E3AF6C9CA71C96E23892AB45D3F5BFDAE1DF20F |
