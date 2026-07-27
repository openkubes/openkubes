#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Transit Vault backup (OK-114) — file-storage snapshot of the auto-unseal provider.
#
# The Transit Vault (ok-mgmt) uses the `file` storage backend, so `vault operator
# raft snapshot` does not apply. This tars its barrier-encrypted storage dir
# (/vault/data) out of the pod, encrypts it to the operator GPG key, writes it
# off-host, and records an integrity row. Recovery: recreate the Transit Vault,
# restore /vault/data, start, unseal with the Transit Shamir shares
# (~/transit-init.json.gpg — verified custody).
#
# The Transit key is essentially static (created once), so a live tar is safe in
# practice for this rarely-written Vault; take a fresh backup after any change to
# the transit engine/keys.
#
# Config via env:
#   GPG_RECIPIENT   (REQUIRED) operator key id the backup is encrypted to.
#   KUBECONFIG      point at ok-mgmt (the Transit Vault host).
#   TRANSIT_NS      default: vault-transit
#   TRANSIT_POD     default: vault-transit-0
#   OFFHOST_DIR     default: $HOME/vault-backups
#   REGISTER        default: <script dir>/transit-backup-register.md
#
# Usage: KUBECONFIG=~/.kube/ok-mgmt.yaml GPG_RECIPIENT=<key> ./transit-backup.sh
# Dependencies: kubectl, gpg, tar, sha256sum|shasum.
# ─────────────────────────────────────────────────────────────────────────────
set -u -o pipefail

: "${GPG_RECIPIENT:?set GPG_RECIPIENT (operator key id)}"
NS="${TRANSIT_NS:-vault-transit}"
POD="${TRANSIT_POD:-vault-transit-0}"
OFFHOST_DIR="${OFFHOST_DIR:-$HOME/vault-backups}"
HERE="$(cd "$(dirname "$0")" && pwd)"
REGISTER="${REGISTER:-$HERE/transit-backup-register.md}"

for bin in kubectl gpg; do command -v "$bin" >/dev/null 2>&1 || { echo "ERROR: '$bin' required" >&2; exit 2; }; done
sha256() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }

TS="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OFFHOST_DIR"
OUT="$OFFHOST_DIR/transit-data-$TS.tar.gz.gpg"

echo "→ tar /vault/data from $NS/$POD → gpg($GPG_RECIPIENT)"
if ! kubectl -n "$NS" exec "$POD" -- tar czf - -C / vault/data 2>/dev/null \
     | gpg --batch --yes --encrypt --recipient "$GPG_RECIPIENT" --output "$OUT"; then
  echo "ERROR: backup pipeline failed" >&2; rm -f "$OUT"; exit 1
fi
[ -s "$OUT" ] || { echo "ERROR: backup is empty" >&2; rm -f "$OUT"; exit 1; }

ENC_SHA="$(sha256 "$OUT")"
SIZE="$(wc -c <"$OUT" | tr -d ' ')"

if [ ! -f "$REGISTER" ]; then
  {
    echo "# Transit Vault backup register (OK-114)"
    echo
    echo "Encrypted \`file\`-storage snapshots of the Transit Vault (auto-unseal provider)."
    echo "No secret material in this file — hashes + paths only. Recovery also needs"
    echo "the Transit Shamir shares (~/transit-init.json.gpg)."
    echo
    echo "| Timestamp (UTC) | File | Size (B) | SHA-256 (encrypted) | Recipient |"
    echo "|---|---|---|---|---|"
  } >"$REGISTER"
fi
printf '| %s | %s | %s | %s | %s |\n' "$TS" "$(basename "$OUT")" "$SIZE" "$ENC_SHA" "$GPG_RECIPIENT" >>"$REGISTER"

echo "----"
echo "backup : $OUT"
echo "size   : $SIZE B"
echo "sha256 : $ENC_SHA"
echo "register: $REGISTER"
echo "RESULT: transit backup taken + registered. (Recovery also needs the Transit Shamir shares.)"
