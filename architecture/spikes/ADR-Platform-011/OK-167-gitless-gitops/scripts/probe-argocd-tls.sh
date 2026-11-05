#!/usr/bin/env bash
# Verify the Argo CD API endpoint without insecure client flags.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"
KUBECTL="${KUBECTL:-kubectl}"
umask 077
WORK="$(mktemp -d "$ROOT/.local/tmp/argocd-tls.XXXXXX")"
PID=''
cleanup() { if [ -n "$PID" ]; then kill "$PID" 2>/dev/null || true; wait "$PID" 2>/dev/null || true; fi; rm -rf "$WORK"; }
trap cleanup EXIT
# Extract only the public certificate into a private temporary file. No Secret
# object, password or private key is printed or persisted as evidence.
"$KUBECTL" -n argocd get secret argocd-secret -o jsonpath='{.data.tls\.crt}' \
  | base64 -d > "$WORK/server.crt"
"$KUBECTL" -n argocd port-forward --address 127.0.0.1 service/argocd-server 30443:443 \
  > "$WORK/forward.log" 2>&1 &
PID=$!
code=''
for attempt in {1..30}; do
  : "$attempt"
  code=$(curl -s --cacert "$WORK/server.crt" -o /dev/null -w '%{http_code}' \
    https://localhost:30443/healthz) && [ "$code" = 200 ] && break
  sleep 1
done
[ "$code" = 200 ] || { echo 'Argo CD API TLS probe failed' >&2; exit 1; }
rejection=0
curl -s -o /dev/null https://localhost:30443/healthz || rejection=$?
[ "$rejection" = 60 ] || { echo 'Untrusted API certificate was not rejected' >&2; exit 1; }
flag=$("$KUBECTL" -n argocd get cm argocd-cmd-params-cm -o jsonpath='{.data.server\.insecure}')
[ "$flag" = false ] || exit 1
if [ "${1:-probe}" = webhook ]; then
  jq '.body' evidence/raw/cloudevent-image-updated.json > "$WORK/event.json"
  code=$(curl -sS --cacert "$WORK/server.crt" -o "$WORK/response.txt" -w '%{http_code}' \
    -H 'Content-Type: application/json' -H 'ce-type: zotregistry.image.updated' \
    -H 'ce-source: zotregistry.dev' -H 'ce-specversion: 1.0' -H 'ce-id: review-replay' \
    --data-binary "@$WORK/event.json" https://localhost:30443/api/webhook)
  [ "$code" = 400 ] && grep -q 'Unknown webhook event' "$WORK/response.txt"
  jq -n --argjson http "$code" --rawfile response "$WORK/response.txt" \
    '{test:"Q3.c",tls_verified:true,http_status:$http,response:$response,result:"PASS"}'
else
  jq -n --argjson http "$code" --argjson rejected "$rejection" \
    '{test:"API TLS",server_insecure:false,http_status:$http,untrusted_curl_exit:$rejected,result:"PASS"}'
fi
