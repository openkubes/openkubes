#!/usr/bin/env bash
# Prove zot GC reclamation and scrub integrity on ok-shared.
set -Eeuo pipefail
set +x

for command_name in base64 curl jq sha256sum; do
  command -v "$command_name" >/dev/null 2>&1 || { echo "ERROR: $command_name is required" >&2; exit 2; }
done

REGISTRY_HOST="${REGISTRY_HOST:-registry.ok-shared.internal}"
REGISTRY_IP="${REGISTRY_IP:-${REGISTRY_LB:-192.168.100.207}}"
REGISTRY_PORT="${REGISTRY_PORT:-443}"
KUBE_CONTEXT="${KUBE_CONTEXT:-}"
KUBECONFIG="${KUBECONFIG:-}"
NAMESPACE="${NAMESPACE:-${REGISTRY_NAMESPACE:-zot}}"
RELEASE="${RELEASE:-zot}"
CREDENTIAL_SECRET="${CREDENTIAL_SECRET:-zot-machine-identities}"
TLS_SECRET="${TLS_SECRET:-zot-server-tls}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="${RESULTS_DIR:-${SCRIPT_DIR}/results-lifecycle}"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dt%H%M%Sz)}"
GC_TIMEOUT="${GC_TIMEOUT:-240}"
SCRUB_TIMEOUT="${SCRUB_TIMEOUT:-180}"
# Must exceed storage.gcDelay: zot refuses to reclaim a blob younger than that grace
# period, so a shorter settle makes the first post-restart GC pass a no-op and the
# assertion fails against a perfectly healthy registry (observed on ok-shared
# 2026-08-10 with a 12s settle against a 1m gcDelay).
#
# values-ok-shared.yaml ships gcDelay/gcInterval at 1h -- the zot default, and the only
# safe production value: a grace period shorter than a slow multi-GB push lets GC reap
# that push's own blobs before its manifest PUT lands, which surfaces as intermittent
# MANIFEST_BLOB_UNKNOWN under load. Waiting out 1h here is not viable, so this contract
# requires a GC-tuned deployment and is NOT part of OK-138 Increment 1 evidence. Run it
# against a disposable registry with gcDelay/gcInterval lowered, and pass a settle
# delay that exceeds the value you set.
GC_SETTLE_DELAY="${GC_SETTLE_DELAY:-75}"
ENDPOINT="https://${REGISTRY_HOST}:${REGISTRY_PORT}"
DISPOSABLE_REPO="openkubes/machine/000-lifecycle/disposable-${RUN_ID}"
RETAINED_REPO="openkubes/machine/000-lifecycle/retained-${RUN_ID}"

case "$RUN_ID" in (*[!A-Za-z0-9._-]*|'') echo "ERROR: RUN_ID contains unsafe characters" >&2; exit 2;; esac
for numeric in GC_TIMEOUT SCRUB_TIMEOUT GC_SETTLE_DELAY; do
  [[ "${!numeric}" =~ ^[0-9]+$ ]] || { echo "ERROR: $numeric must be numeric" >&2; exit 2; }
done
case "$RESULTS_DIR" in (/*) ;; (*) RESULTS_DIR="${PWD}/${RESULTS_DIR}";; esac
RUN_RESULTS_DIR="${RESULTS_DIR}/${RUN_ID}"
test ! -e "$RUN_RESULTS_DIR" || { echo "ERROR: results already exist: $RUN_RESULTS_DIR" >&2; exit 2; }
mkdir -p "$RUN_RESULTS_DIR"
WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/zot-lifecycle.XXXXXX")"
trap 'rm -rf -- "$WORKDIR"' EXIT INT TERM
umask 077
exec > >(tee "${RUN_RESULTS_DIR}/summary.log") 2>&1

read -r -a KUBECTL <<< "${KUBECTL:-kubectl}"
command -v "${KUBECTL[0]}" >/dev/null 2>&1 || { echo "ERROR: ${KUBECTL[0]} is required" >&2; exit 2; }
[[ -z "$KUBECONFIG" ]] || KUBECTL+=(--kubeconfig "$KUBECONFIG")
[[ -z "$KUBE_CONTEXT" ]] || KUBECTL+=(--context "$KUBE_CONTEXT")
secret_value() {
  local key="$1"
  "${KUBECTL[@]}" -n "$NAMESPACE" get secret "$CREDENTIAL_SECRET" -o json |
    jq -er --arg key "$key" '.data[$key]' | base64 -d
}
MACHINE_USER="$(secret_value machine-username)"
MACHINE_PASS="$(secret_value machine-password)"
[[ -n "$MACHINE_USER" && -n "$MACHINE_PASS" ]] || { echo "ERROR: machine credential is empty" >&2; exit 2; }

CA_FILE="${REGISTRY_CA_FILE:-$WORKDIR/ca.crt}"
if [[ -z "${REGISTRY_CA_FILE:-}" ]]; then
  "${KUBECTL[@]}" -n "$NAMESPACE" get secret "$TLS_SECRET" -o json |
    jq -er '.data["ca.crt"]' | base64 -d > "$CA_FILE"
fi
[[ -s "$CA_FILE" ]] || { echo "ERROR: CA bundle is empty" >&2; exit 2; }
RESOLVE=(--resolve "${REGISTRY_HOST}:${REGISTRY_PORT}:${REGISTRY_IP}")

registry_curl() {
  local auth config_fd rc
  auth="$(printf '%s:%s' "$MACHINE_USER" "$MACHINE_PASS" | base64 | tr -d '\n')"
  exec {config_fd}< <(printf 'header = "Authorization: Basic %s"\n' "$auth")
  curl --cacert "$CA_FILE" "${RESOLVE[@]}" --config "/dev/fd/${config_fd}" "$@"; rc=$?
  exec {config_fd}<&-
  unset auth
  return "$rc"
}
pass() { printf '  PASS  %s\n' "$*"; }
digest_file() { printf 'sha256:%s' "$(sha256sum "$1" | awk '{print $1}')"; }
put_blob() {
  local repo="$1" file="$2" digest="$3" code location separator
  code="$(registry_curl -sS -D "$WORKDIR/headers" -o /dev/null -w '%{http_code}' -X POST "$ENDPOINT/v2/$repo/blobs/uploads/")"
  [[ "$code" == 202 ]] || { echo "ERROR: blob upload start returned $code" >&2; return 1; }
  location="$(awk 'BEGIN{IGNORECASE=1} /^Location:/ {sub(/^[^:]+:[[:space:]]*/,""); sub(/\r$/,""); print; exit}' "$WORKDIR/headers")"
  [[ -n "$location" ]] || { echo "ERROR: registry omitted upload Location" >&2; return 1; }
  if [[ "$location" == http://* || "$location" == https://* ]]; then
    location="${location#*://}"; location="${ENDPOINT}/${location#*/}"
  else
    location="${ENDPOINT}${location}"
  fi
  separator='?'; [[ "$location" == *\?* ]] && separator='&'
  code="$(registry_curl -sS -o /dev/null -w '%{http_code}' -X PUT --data-binary "@$file" "${location}${separator}digest=${digest}")"
  [[ "$code" == 201 ]] || { echo "ERROR: blob upload returned $code" >&2; return 1; }
}
put_artifact() {
  local repo="$1" payload="$2" manifest_out="$3" manifest_var="$4" blob_var="$5" blob digest code
  blob="$(digest_file "$payload")"; printf '{}' > "$WORKDIR/empty-config.json"; digest="$(digest_file "$WORKDIR/empty-config.json")"
  put_blob "$repo" "$WORKDIR/empty-config.json" "$digest"; put_blob "$repo" "$payload" "$blob"
  jq -n --arg c "$digest" --argjson cs "$(wc -c < "$WORKDIR/empty-config.json")" --arg b "$blob" --argjson bs "$(wc -c < "$payload")" \
    '{schemaVersion:2,mediaType:"application/vnd.oci.image.manifest.v1+json",artifactType:"application/vnd.openkubes.lifecycle.v1",config:{mediaType:"application/vnd.oci.empty.v1+json",digest:$c,size:$cs},layers:[{mediaType:"application/octet-stream",digest:$b,size:$bs}]}' > "$manifest_out"
  code="$(registry_curl -sS -o "$WORKDIR/response" -w '%{http_code}' -X PUT -H 'Content-Type: application/vnd.oci.image.manifest.v1+json' --data-binary "@$manifest_out" "$ENDPOINT/v2/$repo/manifests/proof")"
  [[ "$code" == 201 ]] || { echo "ERROR: artifact manifest upload returned $code" >&2; return 1; }
  printf -v "$manifest_var" '%s' "$(digest_file "$manifest_out")"
  printf -v "$blob_var" '%s' "$blob"
}
status_for() {
  local code
  if code="$(registry_curl -sS -o /dev/null -w '%{http_code}' "$1" 2>/dev/null)"; then printf '%s' "$code"; else printf '000'; fi
}

printf 'disposable lifecycle payload %s\n' "$RUN_ID" > "$WORKDIR/disposable.txt"
printf 'retained lifecycle payload %s\n' "$RUN_ID" > "$WORKDIR/retained.txt"

echo "1. Push disposable and retained artifacts"
put_artifact "$DISPOSABLE_REPO" "$WORKDIR/disposable.txt" "$WORKDIR/disposable-manifest.json" DISPOSABLE_MANIFEST DISPOSABLE_BLOB
put_artifact "$RETAINED_REPO" "$WORKDIR/retained.txt" "$WORKDIR/retained-manifest.json" RETAINED_MANIFEST RETAINED_BLOB
[[ "$(status_for "$ENDPOINT/v2/$DISPOSABLE_REPO/blobs/$DISPOSABLE_BLOB")" == 200 ]]
[[ "$(status_for "$ENDPOINT/v2/$RETAINED_REPO/blobs/$RETAINED_BLOB")" == 200 ]]
pass "both unique RUN_ID blobs are initially reachable"

echo "2. Delete only the disposable manifest"
code="$(registry_curl -sS -o /dev/null -w '%{http_code}' -X DELETE "$ENDPOINT/v2/$DISPOSABLE_REPO/manifests/$DISPOSABLE_MANIFEST")"
[[ "$code" == 202 ]] || { echo "ERROR: manifest deletion returned $code" >&2; exit 1; }
[[ "$(status_for "$ENDPOINT/v2/$DISPOSABLE_REPO/manifests/$DISPOSABLE_MANIFEST")" == 404 ]]
pass "disposable manifest is no longer retrievable"

echo "3. Restart zot and assert GC effect while retained content survives"
sleep "$GC_SETTLE_DELAY"
STATEFULSET="$("${KUBECTL[@]}" -n "$NAMESPACE" get statefulset -l "app.kubernetes.io/instance=${RELEASE},app.kubernetes.io/name=zot" -o json | jq -er '.items | if length == 1 then .[0].metadata.name else error("expected exactly one zot StatefulSet") end')"
"${KUBECTL[@]}" -n "$NAMESPACE" rollout restart "statefulset/$STATEFULSET" >/dev/null
"${KUBECTL[@]}" -n "$NAMESPACE" rollout status "statefulset/$STATEFULSET" --timeout=120s
POD="$("${KUBECTL[@]}" -n "$NAMESPACE" get pod -l "app.kubernetes.io/instance=${RELEASE},app.kubernetes.io/name=zot" -o json | jq -er '.items | map(select(.status.phase == "Running")) | if length == 1 then .[0].metadata.name else error("expected exactly one running zot Pod") end')"
deadline=$((SECONDS + GC_TIMEOUT)); disposable_status=000; retained_status=000
while (( SECONDS < deadline )); do
  disposable_status="$(status_for "$ENDPOINT/v2/$DISPOSABLE_REPO/blobs/$DISPOSABLE_BLOB")"
  retained_status="$(status_for "$ENDPOINT/v2/$RETAINED_REPO/blobs/$RETAINED_BLOB")"
  [[ "$disposable_status" == 404 && "$retained_status" == 200 ]] && break
  sleep 5
done
[[ "$disposable_status" == 404 ]] || { echo "ERROR: orphan blob remains reachable ($disposable_status)" >&2; exit 1; }
[[ "$retained_status" == 200 ]] || { echo "ERROR: retained blob became unreachable ($retained_status)" >&2; exit 1; }
pass "GC reclaimed the orphan and preserved the referenced blob"

echo "4. Assert scrub completed and retained bytes remain intact"
scrub_marker="scrub successfully completed for /var/lib/registry/${RETAINED_REPO}"
deadline=$((SECONDS + SCRUB_TIMEOUT)); scrub_seen=false
while (( SECONDS < deadline )); do
  "${KUBECTL[@]}" -n "$NAMESPACE" logs "$POD" --since=10m > "$WORKDIR/zot.log"
  if grep -Fq "$scrub_marker" "$WORKDIR/zot.log"; then scrub_seen=true; break; fi
  sleep 5
done
[[ "$scrub_seen" == true ]] || { echo "ERROR: scrub completion effect was not observed" >&2; exit 1; }
# Positive control first. Without it this check fails OPEN: if zot ever renames the
# field or prefixes the repo path, the selector matches nothing, the pipeline is false,
# and we would print PASS having verified nothing at all.
if ! grep -Fq "\"image\":\"${RETAINED_REPO}\"" "$WORKDIR/zot.log"; then
  echo "ERROR: scrub log has no entry for ${RETAINED_REPO}; the damage selector matched nothing and cannot be trusted" >&2
  exit 1
fi
if grep -F "\"image\":\"${RETAINED_REPO}\"" "$WORKDIR/zot.log" | grep -Fq '"status":"affected"'; then
  echo "ERROR: scrub reported affected retained content" >&2; exit 1
fi
code="$(registry_curl -sS -o "$WORKDIR/retained-after-scrub" -w '%{http_code}' "$ENDPOINT/v2/$RETAINED_REPO/blobs/$RETAINED_BLOB")"
[[ "$code" == 200 && "$(digest_file "$WORKDIR/retained-after-scrub")" == "$RETAINED_BLOB" ]] || { echo "ERROR: retained blob bytes failed digest verification after scrub" >&2; exit 1; }
pass "scrub completed without changing retained content"

cat > "${RUN_RESULTS_DIR}/results.env" <<EOF
disposable=https://${REGISTRY_HOST}/${DISPOSABLE_REPO}@${DISPOSABLE_MANIFEST}
disposable_blob=${DISPOSABLE_BLOB}
retained=https://${REGISTRY_HOST}/${RETAINED_REPO}@${RETAINED_MANIFEST}
retained_blob=${RETAINED_BLOB}
gc=PASS
scrub=PASS
result=PASS
EOF
echo "Lifecycle contract: PASS"
echo "Evidence: $RUN_RESULTS_DIR"
