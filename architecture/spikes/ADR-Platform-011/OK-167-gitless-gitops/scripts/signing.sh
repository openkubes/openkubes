#!/usr/bin/env bash
# Digest-based signing and verification. No transparency log or TUF service is used.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
# shellcheck disable=SC1091
. "$ROOT/versions.env"
cd "$ROOT"
ACTION="${1:?sign or verify required}"
DIGEST="${DIGEST:?DIGEST is required}"
REPO="${REPO:-$REPO_MANIFESTS}"
MODE="${MODE:-bundle}"
case "$DIGEST" in sha256:*) : ;; *) ok167::die "use an artifact digest" 2 ;; esac
case "$REPO" in "$REPO_PREFIX/"*) : ;; *) ok167::die "repository outside the spike prefix" 2 ;; esac
case "$MODE" in bundle) BUNDLE=true ;; legacy) BUNDLE=false ;; *) ok167::die "MODE=bundle or legacy" 2 ;; esac
umask 077
KEY_DIR="$ROOT/.local/revision-cosign"
AUTH_DIR="$ROOT/.local/revision-docker"
mkdir -p "$KEY_DIR" "$AUTH_DIR" .local/tmp
if [ ! -f "$KEY_DIR/password" ]; then
  "${OPENSSL:-openssl}" rand -base64 32 > "$KEY_DIR/password"
fi
COSIGN_PASSWORD="$(< "$KEY_DIR/password")"
export COSIGN_PASSWORD
LOG="$ROOT/.local/tmp/signing.$$.log"
trap 'rm -f "$LOG"; unset COSIGN_PASSWORD' EXIT
if [ ! -f "$KEY_DIR/cosign.key" ]; then
  "${COSIGN:-cosign}" generate-key-pair --output-key-prefix "$KEY_DIR/cosign" > "$LOG" 2>&1
fi
chmod 600 "$KEY_DIR/"*
ok167::credential OK167_GITOPS_PUBLISHER_PASSWORD \
  | "${ORAS:-oras}" login "$ZOT_HOST" --username "$IDENTITY_PUBLISHER" --password-stdin \
      --ca-file .local/pki/ca.crt --registry-config "$AUTH_DIR/config.json" > "$LOG" 2>&1
REF="$ZOT_HOST/$REPO@$DIGEST"
case "$ACTION" in
  sign)
    # Upload the public key before signing; do not include its value in evidence.
    code=$(curl -sS --cacert .local/pki/ca.crt --netrc-file .local/netrc-ok167-admin \
      -o /dev/null -w '%{http_code}' -X POST --data-binary "@$KEY_DIR/cosign.pub" \
      "https://$ZOT_HOST/v2/_zot/ext/cosign")
    [ "$code" = 200 ] || ok167::die "trust key upload failed" 1
    DOCKER_CONFIG="$AUTH_DIR" "${COSIGN:-cosign}" sign --key "$KEY_DIR/cosign.key" \
      --use-signing-config=false --tlog-upload=false --new-bundle-format="$BUNDLE" \
      --registry-cacert .local/pki/ca.crt -y "$REF" > "$LOG" 2>&1 \
      || ok167::die "offline signing failed; private diagnostics remain in .local/" 1
    ;;
  verify)
    DOCKER_CONFIG="$AUTH_DIR" "${COSIGN:-cosign}" verify --key "$KEY_DIR/cosign.pub" \
      --insecure-ignore-tlog=true --new-bundle-format="$BUNDLE" \
      --registry-cacert .local/pki/ca.crt "$REF" > "$LOG" 2>&1 \
      || ok167::die "signature verification failed" 1
    ;;
  *) ok167::die "expected sign or verify" 2 ;;
esac
jq -nc --arg action "$ACTION" --arg digest "$DIGEST" --arg repo "$REPO" --arg mode "$MODE" \
  '{action:$action,digest:$digest,repository:$repo,format:$mode,result:"PASS",tlog_upload:false}'
