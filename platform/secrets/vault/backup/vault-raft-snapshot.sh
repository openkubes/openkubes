#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Vault Raft snapshot helper — ADR-Platform-025 crit. 11 / A10 backup model.
#
# Takes a consistent integrated-storage snapshot, hashes it, GPG-encrypts it to
# the custodian key, optionally copies it off-host, and appends a row to the
# backup register. The plaintext snapshot only ever lives in a private tmp dir
# and is removed on exit (shred if available). See:
#   runbooks/vault-backup-operating-model.md
#
# This is the only mutating helper here, and it is NON-DESTRUCTIVE: it reads
# Vault state (snapshot save) — it does not restore, delete, or reconfigure.
#
# Config via env:
#   VAULT_TOKEN     (REQUIRED) break-glass/admin token with snapshot capability.
#                   Pass via env/stdin — never on argv or in shell history.
#   GPG_RECIPIENT   (REQUIRED) key id the snapshot is encrypted to (unseal-share custody).
#   VAULT_CONTEXT   kube context for Vault (e.g. ok-shared).
#   VAULT_NS        Vault namespace (default: vault).
#   VAULT_POD       snapshot source pod (default: auto-resolve the active/leader pod).
#   WORKDIR         where the .gpg lands locally (default: $HOME/vault-backups — never the repo).
#   OFFHOST_DIR     optional: also copy the .gpg here (off the ok-shared failure domain).
#   REGISTER        register file to append to (default: backup/backup-register.md).
#   RETENTION_DAYS  retention window recorded in the register (default: 7).
#
# Usage: VAULT_TOKEN=… GPG_RECIPIENT=… ./vault-raft-snapshot.sh
# Dependencies: kubectl, gpg, sha256sum|shasum, date.
# ─────────────────────────────────────────────────────────────────────────────
set -u -o pipefail

VAULT_NS="${VAULT_NS:-vault}"
VAULT_POD="${VAULT_POD:-}"   # empty → auto-resolve the active (leader) pod below
WORKDIR="${WORKDIR:-$HOME/vault-backups}"   # NEVER default into the repo tree
REGISTER="${REGISTER:-backup/backup-register.md}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

: "${VAULT_TOKEN:?set VAULT_TOKEN (break-glass token; via env/stdin, not argv)}"
: "${GPG_RECIPIENT:?set GPG_RECIPIENT (custodian key id for at-rest encryption)}"

for bin in kubectl gpg date; do
  command -v "$bin" >/dev/null 2>&1 || { echo "ERROR: '$bin' is required" >&2; exit 2; }
done
sha256() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
secure_rm() {
  if command -v shred >/dev/null 2>&1; then shred -u "$1" 2>/dev/null || rm -f "$1";
  elif command -v gshred >/dev/null 2>&1; then gshred -u "$1" 2>/dev/null || rm -f "$1";
  else rm -f "$1"; fi
}
retention_until() { # portable +N days (GNU then BSD)
  date -u -d "+$1 days" +%F 2>/dev/null || date -u -v+"$1"d +%F 2>/dev/null || echo "unknown"
}

VC=(kubectl); [ -n "${VAULT_CONTEXT:-}" ] && VC=(kubectl --context "$VAULT_CONTEXT")

# Resolve the ACTIVE (leader) pod unless pinned. `snapshot save` on a standby is
# redirected to the leader's cluster address, whose TLS cert is valid only for
# 127.0.0.1 → the redirect fails. The Vault Helm chart labels the active pod
# `vault-active=true` (same selector the vault-active Service uses).
if [ -z "$VAULT_POD" ]; then
  VAULT_POD="$("${VC[@]}" -n "$VAULT_NS" get pods -l vault-active=true \
                -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)"
  [ -n "$VAULT_POD" ] || VAULT_POD="vault-0"
  echo "active pod: $VAULT_POD (auto-resolved; override with VAULT_POD=)"
fi

TS="$(date -u +%Y%m%dT%H%M%SZ)"
SNAP="vault-${TS}.snap"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/vault-snap.XXXXXX")"
cleanup() { [ -f "$TMP/$SNAP" ] && secure_rm "$TMP/$SNAP"; rm -rf "$TMP"; }
trap cleanup EXIT

echo "Vault Raft snapshot (crit. 11 / A10)"
echo "------------------------------------"

# 1. Snapshot inside the pod (token via env, not argv), then copy out and remove.
echo "→ snapshot save on $VAULT_NS/$VAULT_POD"
if ! "${VC[@]}" -n "$VAULT_NS" exec -i "$VAULT_POD" -- \
      env VAULT_TOKEN="$VAULT_TOKEN" vault operator raft snapshot save "/tmp/$SNAP" >/dev/null; then
  echo "ERROR: snapshot save failed (token capability? pod sealed?)" >&2; exit 1
fi
"${VC[@]}" -n "$VAULT_NS" cp "$VAULT_NS/$VAULT_POD:/tmp/$SNAP" "$TMP/$SNAP" >/dev/null
"${VC[@]}" -n "$VAULT_NS" exec "$VAULT_POD" -- rm -f "/tmp/$SNAP" >/dev/null 2>&1 || true
[ -s "$TMP/$SNAP" ] || { echo "ERROR: copied snapshot is empty" >&2; exit 1; }

PLAIN_SHA="$(sha256 "$TMP/$SNAP")"
SIZE="$(wc -c <"$TMP/$SNAP" | tr -d ' ')"

# 2. Encrypt at rest to the custodian key.
echo "→ gpg encrypt to $GPG_RECIPIENT"
if ! gpg --yes --batch --encrypt --recipient "$GPG_RECIPIENT" --output "$TMP/$SNAP.gpg" "$TMP/$SNAP"; then
  echo "ERROR: gpg encryption failed (recipient key present?)" >&2; exit 1
fi
ENC_SHA="$(sha256 "$TMP/$SNAP.gpg")"
secure_rm "$TMP/$SNAP"    # plaintext gone immediately

# 3. Place the encrypted artifact locally and (optionally) off-host.
mkdir -p "$WORKDIR"; install -m 0600 "$TMP/$SNAP.gpg" "$WORKDIR/$SNAP.gpg"
DEST="$WORKDIR/$SNAP.gpg"
OFFHOST_STATUS="(not set — copy off-host manually)"
if [ -n "${OFFHOST_DIR:-}" ]; then
  mkdir -p "$OFFHOST_DIR"; install -m 0600 "$TMP/$SNAP.gpg" "$OFFHOST_DIR/$SNAP.gpg"
  OFFHOST_STATUS="$OFFHOST_DIR/$SNAP.gpg"
fi
UNTIL="$(retention_until "$RETENTION_DAYS")"

# 4. Append to the backup register.
mkdir -p "$(dirname "$REGISTER")"
if [ ! -f "$REGISTER" ]; then
  {
    echo "# Vault backup register (ADR-025 crit. 11 / A10)"
    echo
    echo "| Timestamp (UTC) | File | Size (B) | SHA-256 (plaintext) | SHA-256 (encrypted) | Recipient | Off-host | Retain until | Restore-tested |"
    echo "|---|---|---|---|---|---|---|---|---|"
  } >"$REGISTER"
fi
printf '| %s | %s | %s | %s | %s | %s | %s | %s | %s |\n' \
  "$TS" "$SNAP.gpg" "$SIZE" "$PLAIN_SHA" "$ENC_SHA" "$GPG_RECIPIENT" "$OFFHOST_STATUS" "$UNTIL" "no" \
  >>"$REGISTER"

echo "------------------------------------"
echo "encrypted snapshot : $DEST"
echo "size (plaintext)   : $SIZE bytes"
echo "sha256 plaintext   : $PLAIN_SHA"
echo "sha256 encrypted   : $ENC_SHA"
echo "off-host copy      : $OFFHOST_STATUS"
echo "retain until       : $UNTIL"
echo "registered in      : $REGISTER"
[ -n "${OFFHOST_DIR:-}" ] || echo "NOTE: OFFHOST_DIR unset — a snapshot on one host is NOT yet a backup. Copy it off the ok-shared failure domain."
echo "RESULT: snapshot taken, encrypted, and registered."
