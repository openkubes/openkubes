#!/usr/bin/env bash
# OK-81 — break-glass: regain admin access to a running Keycloak when no known admin credential
# works. Uses Keycloak's own supported command (`kc.sh bootstrap-admin user`), which writes a new
# admin straight to the database of the RUNNING server, so no restart and no data loss.
#
# The account it creates is a TEMPORARY admin (Keycloak stamps is_temporary_admin=true on it), so
# recovery is deliberately not the end state: follow it with keycloak-admin-cutover.sh.
#
# The password is generated here, escrowed to Vault immediately, and passed to the pod through an
# environment variable name (--password:env), never as an argument.
set -Eeuo pipefail

: "${KUBECTL:?KUBECTL is required}"
: "${KUBECONFIG:?KUBECONFIG is required}"
: "${NAMESPACE:?NAMESPACE is required}"
: "${KEYCLOAK_POD:?KEYCLOAK_POD is required}"
: "${RECOVERY_USERNAME:?RECOVERY_USERNAME is required}"
: "${KV_RECOVERY_PATH:?KV_RECOVERY_PATH is required}"
: "${KV_PUT_SCRIPT:?KV_PUT_SCRIPT is required}"
CA="$1"

# The work dir is RETAINED. A cleanup trap here once destroyed the only copy of a generated admin
# password when a later step failed, which is precisely the material recovery exists to protect.
# It is mode 700 and holds plaintext credentials: delete it yourself once they are escrowed.
umask 077
_d="$(mktemp -d)"
keep() { echo "      work dir RETAINED (mode 700, contains plaintext credentials): $_d"; }
trap keep EXIT INT TERM
keep

echo "[1/3] generate the recovery password and escrow it BEFORE creating the account"
openssl rand -base64 32 | tr -d '\n' > "$_d/pw"
[ -s "$_d/pw" ] || { echo "ABORT: empty password" >&2; exit 1; }
python3 - "$_d" "$RECOVERY_USERNAME" <<'PY'
import json,sys
d,u=sys.argv[1],sys.argv[2]
json.dump({"username":u,"password":open(f"{d}/pw").read()}, open(f"{d}/kv.json","w"))
PY
bash "$KV_PUT_SCRIPT" "$CA" "$KV_RECOVERY_PATH" "$_d/kv.json"

echo "[2/3] create the temporary admin $RECOVERY_USERNAME inside $KEYCLOAK_POD"
# The username is not a secret, so it travels as an argument; the password is read from stdin
# inside the pod and handed to kc.sh by variable NAME only.
# bootstrap-admin boots a partial server, which tries to bind 8080 and the 9000 management port —
# both already held by the Keycloak process running in this very pod ("Address already in use").
# Point this short-lived JVM at unused ports; it only needs the database, not a listener.
"$KUBECTL" --kubeconfig "$KUBECONFIG" exec -i -n "$NAMESPACE" "$KEYCLOAK_POD" -c keycloak -- \
  env "KC_RECOVERY_USERNAME=$RECOVERY_USERNAME" \
      KC_HTTP_PORT=8099 KC_HTTP_MANAGEMENT_PORT=9099 \
  sh -c 'read -r p; export KC_RECOVERY_PW="$p";
         /opt/keycloak/bin/kc.sh bootstrap-admin user --no-prompt \
           --username "$KC_RECOVERY_USERNAME" --password:env KC_RECOVERY_PW' \
  < "$_d/pw"

echo "[3/3] done"
echo "      temporary admin $RECOVERY_USERNAME created; password escrowed at $KV_RECOVERY_PATH"
echo "      NEXT: run the cutover to replace it with a permanent admin, then delete this KV path."
