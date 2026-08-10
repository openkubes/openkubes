#!/usr/bin/env bash
# registry-default (zot) conformance smoke test for ok-shared (OK-138).
#
# This proves the OCI contract from a client and from inside a running Pod.  It
# deliberately does not claim the kubelet image-pull boundary: node DNS and the
# internal CA in containerd trust are separate ok-cluster work.
set -Eeuo pipefail
set +x

for command_name in awk base64 cmp curl helm jq sha256sum tar; do
  command -v "$command_name" >/dev/null 2>&1 || { echo "ERROR: $command_name is required" >&2; exit 2; }
done

SCRIPT_SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./registry-defaults.sh
. "$SCRIPT_SELF_DIR/../tooling/registry-defaults.sh"
REGISTRY_IP="${REGISTRY_IP:-$REGISTRY_LB}"
REGISTRY_PORT="${REGISTRY_PORT:-443}"
KUBE_CONTEXT="${KUBE_CONTEXT:-}"
KUBECONFIG="${KUBECONFIG:-}"
NAMESPACE="${NAMESPACE:-${REGISTRY_NAMESPACE:-zot}}"
CREDENTIAL_SECRET="${CREDENTIAL_SECRET:-zot-machine-identities}"
TLS_SECRET="${TLS_SECRET:-zot-server-tls}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="${RESULTS_DIR:-${SCRIPT_DIR}/results-smoke}"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dt%H%M%Sz)}"
REPOSITORY="openkubes/machine/conformance-${RUN_ID}"
ENDPOINT="https://${REGISTRY_HOST}:${REGISTRY_PORT}"

case "$RUN_ID" in (*[!A-Za-z0-9._-]*|'') echo "ERROR: RUN_ID contains unsafe characters" >&2; exit 2;; esac
case "$RESULTS_DIR" in (/*) ;; (*) RESULTS_DIR="${PWD}/${RESULTS_DIR}";; esac
RUN_RESULTS_DIR="${RESULTS_DIR}/${RUN_ID}"
test ! -e "$RUN_RESULTS_DIR" || { echo "ERROR: results already exist: $RUN_RESULTS_DIR" >&2; exit 2; }
mkdir -p "$RUN_RESULTS_DIR"
WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/zot-smoke.XXXXXX")"
JOB_NAME="zot-contract-$(printf '%s' "$RUN_ID" | tr '[:upper:]_.' '[:lower:]--' | cut -c1-40)"
JOB_CREATED=false
cleanup() {
  if [[ "$JOB_CREATED" == true ]]; then
    "${KUBECTL[@]}" -n "$NAMESPACE" delete job "$JOB_NAME" --ignore-not-found --wait=false >/dev/null 2>&1 || true
  fi
  rm -rf -- "$WORKDIR"
}
trap cleanup EXIT INT TERM
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
PULLER_USER="$(secret_value puller-username)"
PULLER_PASS="$(secret_value puller-password)"
METRICS_USER="$(secret_value metrics-username)"
METRICS_PASS="$(secret_value metrics-password)"
for value_name in MACHINE_USER MACHINE_PASS PULLER_USER PULLER_PASS METRICS_USER METRICS_PASS; do
  [[ -n "${!value_name}" ]] || { echo "ERROR: empty credential field $value_name" >&2; exit 2; }
done

CA_FILE="${REGISTRY_CA_FILE:-$WORKDIR/ca.crt}"
if [[ -z "${REGISTRY_CA_FILE:-}" ]]; then
  "${KUBECTL[@]}" -n "$NAMESPACE" get secret "$TLS_SECRET" -o json |
    jq -er '.data["ca.crt"]' | base64 -d > "$CA_FILE"
fi
[[ -s "$CA_FILE" ]] || { echo "ERROR: CA bundle is empty" >&2; exit 2; }
RESOLVE=(--resolve "${REGISTRY_HOST}:${REGISTRY_PORT}:${REGISTRY_IP}")

# Credentials exist only in shell memory and a short-lived inherited FD.  The
# curl argv, evidence files and temporary directory contain no credential.
registry_curl() {
  local identity="$1" user pass auth config_fd rc
  shift
  case "$identity" in
    machine) user="$MACHINE_USER"; pass="$MACHINE_PASS" ;;
    puller) user="$PULLER_USER"; pass="$PULLER_PASS" ;;
    metrics) user="$METRICS_USER"; pass="$METRICS_PASS" ;;
    *) echo "ERROR: unknown identity" >&2; return 2 ;;
  esac
  auth="$(printf '%s:%s' "$user" "$pass" | base64 | tr -d '\n')"
  exec {config_fd}< <(printf 'header = "Authorization: Basic %s"\n' "$auth")
  curl --cacert "$CA_FILE" "${RESOLVE[@]}" --config "/dev/fd/${config_fd}" "$@"; rc=$?
  exec {config_fd}<&-
  unset auth user pass
  return "$rc"
}
pass() { printf '  PASS  %s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
digest_file() { printf 'sha256:%s' "$(sha256sum "$1" | awk '{print $1}')"; }
put_blob() {
  local repo="$1" file="$2" digest="$3" code location
  code="$(registry_curl machine -sS -D "$WORKDIR/headers" -o /dev/null -w '%{http_code}' -X POST "$ENDPOINT/v2/$repo/blobs/uploads/")"
  [[ "$code" == 202 ]] || { echo "ERROR: blob upload start returned $code" >&2; return 1; }
  location="$(awk 'BEGIN{IGNORECASE=1} /^Location:/ {sub(/^[^:]+:[[:space:]]*/,""); sub(/\r$/,""); print; exit}' "$WORKDIR/headers")"
  [[ -n "$location" ]] || { echo "ERROR: registry omitted upload Location" >&2; return 1; }
  if [[ "$location" == http://* || "$location" == https://* ]]; then
    location="${location#*://}"; location="${ENDPOINT}/${location#*/}"
  else
    location="${ENDPOINT}${location}"
  fi
  local separator='?'; [[ "$location" == *\?* ]] && separator='&'
  code="$(registry_curl machine -sS -o /dev/null -w '%{http_code}' -X PUT --data-binary "@$file" "${location}${separator}digest=${digest}")"
  [[ "$code" == 201 ]] || { echo "ERROR: blob upload returned $code" >&2; return 1; }
}
put_manifest() {
  local repo="$1" ref="$2" file="$3" type="$4" code
  code="$(registry_curl machine -sS -o "$WORKDIR/response" -w '%{http_code}' -X PUT -H "Content-Type: $type" --data-binary "@$file" "$ENDPOINT/v2/$repo/manifests/$ref")"
  [[ "$code" == 201 ]] || { echo "ERROR: manifest upload returned $code" >&2; return 1; }
}

# The repository-labelled counter gives a causal discriminator: this run's
# unique repository does not exist before the push, then its upload counter
# must be positive after the exact pushes below.
repo_upload_counter() {
  local file="$1"
  awk -v repo="$REPOSITORY" '
    $1 ~ /^zot_repo_uploads_total\{/ && index($1, "repo=\"" repo "\"") {sum += $2}
    END {print sum + 0}
  ' "$file"
}

registry_curl metrics -sS -o "$WORKDIR/metrics-before" "$ENDPOINT/metrics"
METRICS_BEFORE="$(repo_upload_counter "$WORKDIR/metrics-before")"

step "1. OCI image push, pull, and immutable digest retrieval"
mkdir "$WORKDIR/layer"; printf 'OpenKubes registry conformance %s\n' "$RUN_ID" > "$WORKDIR/layer/proof.txt"
tar -C "$WORKDIR/layer" -cf "$WORKDIR/layer.tar" .
LAYER_DIGEST="$(digest_file "$WORKDIR/layer.tar")"
jq -n --arg diff "$LAYER_DIGEST" '{architecture:"amd64",os:"linux",rootfs:{type:"layers",diff_ids:[$diff]},history:[{created_by:"OpenKubes conformance"}]}' > "$WORKDIR/config.json"
CONFIG_DIGEST="$(digest_file "$WORKDIR/config.json")"
put_blob "$REPOSITORY" "$WORKDIR/config.json" "$CONFIG_DIGEST"
put_blob "$REPOSITORY" "$WORKDIR/layer.tar" "$LAYER_DIGEST"
jq -n --arg cd "$CONFIG_DIGEST" --argjson cs "$(wc -c < "$WORKDIR/config.json")" --arg ld "$LAYER_DIGEST" --argjson ls "$(wc -c < "$WORKDIR/layer.tar")" \
  '{schemaVersion:2,mediaType:"application/vnd.oci.image.manifest.v1+json",config:{mediaType:"application/vnd.oci.image.config.v1+json",digest:$cd,size:$cs},layers:[{mediaType:"application/vnd.oci.image.layer.v1.tar",digest:$ld,size:$ls}]}' > "$WORKDIR/image-manifest.json"
put_manifest "$REPOSITORY" image "$WORKDIR/image-manifest.json" application/vnd.oci.image.manifest.v1+json
IMAGE_DIGEST="$(digest_file "$WORKDIR/image-manifest.json")"
code="$(registry_curl machine -sS -o "$WORKDIR/pulled-layer.tar" -w '%{http_code}' "$ENDPOINT/v2/$REPOSITORY/blobs/$LAYER_DIGEST")"
[[ "$code" == 200 && "$(digest_file "$WORKDIR/pulled-layer.tar")" == "$LAYER_DIGEST" ]] || { echo "ERROR: image layer pull did not reproduce its digest" >&2; exit 1; }
code="$(registry_curl puller -sS -o "$WORKDIR/pulled-manifest.json" -w '%{http_code}' -H 'Accept: application/vnd.oci.image.manifest.v1+json' "$ENDPOINT/v2/$REPOSITORY/manifests/$IMAGE_DIGEST")"
[[ "$code" == 200 && "$(digest_file "$WORKDIR/pulled-manifest.json")" == "$IMAGE_DIGEST" ]] || { echo "ERROR: puller could not retrieve immutable manifest" >&2; exit 1; }
pass "image pushed and pulled by immutable digest $IMAGE_DIGEST"

step "2. OCI Helm chart push and pull"
mkdir -p "$WORKDIR/chart/demo/templates"
printf 'apiVersion: v2\nname: demo\nversion: 0.1.0\n' > "$WORKDIR/chart/demo/Chart.yaml"
printf 'kind: ConfigMap\napiVersion: v1\nmetadata:\n  name: demo\n' > "$WORKDIR/chart/demo/templates/configmap.yaml"
tar -C "$WORKDIR/chart" -czf "$WORKDIR/demo-0.1.0.tgz" demo
printf '{}' > "$WORKDIR/helm-config.json"
HELM_REPO="openkubes/machine/charts/demo-${RUN_ID}"; HC="$(digest_file "$WORKDIR/helm-config.json")"; HL="$(digest_file "$WORKDIR/demo-0.1.0.tgz")"
put_blob "$HELM_REPO" "$WORKDIR/helm-config.json" "$HC"; put_blob "$HELM_REPO" "$WORKDIR/demo-0.1.0.tgz" "$HL"
jq -n --arg c "$HC" --argjson cs "$(wc -c < "$WORKDIR/helm-config.json")" --arg l "$HL" --argjson ls "$(wc -c < "$WORKDIR/demo-0.1.0.tgz")" \
  '{schemaVersion:2,config:{mediaType:"application/vnd.cncf.helm.config.v1+json",digest:$c,size:$cs},layers:[{mediaType:"application/vnd.cncf.helm.chart.content.v1.tar+gzip",digest:$l,size:$ls}]}' > "$WORKDIR/helm-manifest.json"
put_manifest "$HELM_REPO" 0.1.0 "$WORKDIR/helm-manifest.json" application/vnd.oci.image.manifest.v1+json
code="$(registry_curl puller -sS -o "$WORKDIR/pulled-chart.tgz" -w '%{http_code}' "$ENDPOINT/v2/$HELM_REPO/blobs/$HL")"
[[ "$code" == 200 ]] && cmp -s "$WORKDIR/demo-0.1.0.tgz" "$WORKDIR/pulled-chart.tgz" || { echo "ERROR: Helm chart retrieval changed content" >&2; exit 1; }
helm template conformance "$WORKDIR/pulled-chart.tgz" >/dev/null
pass "OCI Helm chart reproduced byte-for-byte and rendered successfully with Helm"

step "3. SBOM attachment and structural Referrers API assertion"
jq -n --arg name "ok-smoke-${RUN_ID}" --arg namespace "https://openkubes.internal/spdx/${RUN_ID}" --arg created "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  '{spdxVersion:"SPDX-2.3",dataLicense:"CC0-1.0",SPDXID:"SPDXRef-DOCUMENT",name:$name,documentNamespace:$namespace,creationInfo:{created:$created,creators:["Tool: openkubes-zot-conformance"]},packages:[]}' > "$WORKDIR/sbom.json"
printf '{}' > "$WORKDIR/artifact-config.json"
AC="$(digest_file "$WORKDIR/artifact-config.json")"; SB="$(digest_file "$WORKDIR/sbom.json")"
put_blob "$REPOSITORY" "$WORKDIR/artifact-config.json" "$AC"; put_blob "$REPOSITORY" "$WORKDIR/sbom.json" "$SB"
jq -n --arg ac "$AC" --argjson acs "$(wc -c < "$WORKDIR/artifact-config.json")" --arg sb "$SB" --argjson sbs "$(wc -c < "$WORKDIR/sbom.json")" --arg subject "$IMAGE_DIGEST" --argjson subject_size "$(wc -c < "$WORKDIR/image-manifest.json")" \
  '{schemaVersion:2,mediaType:"application/vnd.oci.image.manifest.v1+json",artifactType:"application/spdx+json",config:{mediaType:"application/vnd.oci.empty.v1+json",digest:$ac,size:$acs},layers:[{mediaType:"application/spdx+json",digest:$sb,size:$sbs}],subject:{mediaType:"application/vnd.oci.image.manifest.v1+json",digest:$subject,size:$subject_size}}' > "$WORKDIR/sbom-manifest.json"
SBOM_MANIFEST_DIGEST="$(digest_file "$WORKDIR/sbom-manifest.json")"
put_manifest "$REPOSITORY" "sbom-${RUN_ID}" "$WORKDIR/sbom-manifest.json" application/vnd.oci.image.manifest.v1+json
code="$(registry_curl puller -sS -o "$WORKDIR/referrers.json" -w '%{http_code}' -H 'Accept: application/vnd.oci.image.index.v1+json' "$ENDPOINT/v2/$REPOSITORY/referrers/$IMAGE_DIGEST")"
[[ "$code" == 200 ]] || { echo "ERROR: Referrers API returned $code" >&2; exit 1; }
jq -e --arg digest "$SBOM_MANIFEST_DIGEST" '[.manifests[] | select(.digest == $digest and .artifactType == "application/spdx+json")] | length == 1' "$WORKDIR/referrers.json" >/dev/null
code="$(registry_curl puller -sS -o "$WORKDIR/discovered-sbom-manifest.json" -w '%{http_code}' -H 'Accept: application/vnd.oci.image.manifest.v1+json' "$ENDPOINT/v2/$REPOSITORY/manifests/$SBOM_MANIFEST_DIGEST")"
[[ "$code" == 200 ]] && jq -e --arg subject "$IMAGE_DIGEST" '.artifactType == "application/spdx+json" and .subject.digest == $subject and (.layers | length == 1)' "$WORKDIR/discovered-sbom-manifest.json" >/dev/null
pass "Referrers index and discovered manifest preserve the subject-to-SBOM relationship"

step "4. repository authorization has repeatable positive and negative effects"
denied_code="$(registry_curl puller -sS -o /dev/null -w '%{http_code}' -X POST "$ENDPOINT/v2/openkubes/machine/denied-${RUN_ID}/blobs/uploads/")"
[[ "$denied_code" == 401 || "$denied_code" == 403 ]] || { echo "ERROR: puller push returned $denied_code, expected an authz denial" >&2; exit 1; }
code="$(registry_curl puller -sS -o /dev/null -w '%{http_code}' "$ENDPOINT/v2/$REPOSITORY/blobs/$LAYER_DIGEST")"
[[ "$code" == 200 ]] || { echo "ERROR: puller read returned $code" >&2; exit 1; }
pass "puller can read ($code) but a unique RUN_ID repository push is denied ($denied_code)"

step "5. authenticated metrics effect"
code="$(registry_curl metrics -sS -o "$WORKDIR/metrics" -w '%{http_code}' "$ENDPOINT/metrics")"
[[ "$code" == 200 ]] && grep -Eq '(^# (HELP|TYPE) |^zot_)' "$WORKDIR/metrics" || { echo "ERROR: metrics endpoint did not return Prometheus data" >&2; exit 1; }
METRICS_AFTER="$(repo_upload_counter "$WORKDIR/metrics")"
awk -v before="$METRICS_BEFORE" -v after="$METRICS_AFTER" 'BEGIN {exit !(after > before)}' || {
  echo "ERROR: zot_repo_uploads_total for $REPOSITORY did not move ($METRICS_BEFORE -> $METRICS_AFTER)" >&2; exit 1;
}
pass "authenticated metrics returned 200 and zot_repo_uploads_total moved $METRICS_BEFORE -> $METRICS_AFTER for this run"

step "6. IN-CLUSTER CLIENT CONTRACT (not the kubelet pull boundary)"
"${KUBECTL[@]}" -n "$NAMESPACE" apply -f - >/dev/null <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: ${JOB_NAME}
spec:
  ttlSecondsAfterFinished: 300
  template:
    spec:
      restartPolicy: Never
      # Match manifests/contract-job.template.yaml: without these the Job runs with the
      # default ServiceAccount's API token mounted next to the registry credentials, which
      # is strictly more authority than a pull test needs.
      serviceAccountName: zot-contract
      automountServiceAccountToken: false
      securityContext:
        seccompProfile: {type: RuntimeDefault}
      containers:
      - name: pull-contract
        image: docker.io/curlimages/curl:8.12.1@sha256:94e9e444bcba979c2ea12e27ae39bee4cd10bc7041a472c4727a558e213744e6
        command: ["sh", "-ec"]
        args:
        - |
          set +x
          u="\$(cat /credentials/machine-username)"
          p="\$(cat /credentials/machine-password)"
          a="\$(printf '%s:%s' "\$u" "\$p" | base64 | tr -d '\\n')"
          printf 'header = "Authorization: Basic %s"\\n' "\$a" | curl --config - --cacert /tls/ca.crt --resolve '${REGISTRY_HOST}:${REGISTRY_PORT}:${REGISTRY_IP}' -fsS -o /tmp/manifest '${ENDPOINT}/v2/${REPOSITORY}/manifests/${IMAGE_DIGEST}'
          test -s /tmp/manifest
        securityContext:
          allowPrivilegeEscalation: false
          capabilities: {drop: ["ALL"]}
          runAsNonRoot: true
          runAsUser: 100
        volumeMounts:
        - {name: credentials, mountPath: /credentials, readOnly: true}
        - {name: tls, mountPath: /tls, readOnly: true}
      volumes:
      - name: credentials
        secret:
          secretName: ${CREDENTIAL_SECRET}
          items:
          - {key: machine-username, path: machine-username}
          - {key: machine-password, path: machine-password}
      - name: tls
        secret: {secretName: ${TLS_SECRET}, items: [{key: ca.crt, path: ca.crt}]}
EOF
JOB_CREATED=true
if ! "${KUBECTL[@]}" -n "$NAMESPACE" wait --for=condition=complete "job/$JOB_NAME" --timeout=120s >/dev/null; then
  "${KUBECTL[@]}" -n "$NAMESPACE" logs "job/$JOB_NAME" >&2 || true
  echo "ERROR: in-cluster OCI client did not retrieve the digest manifest" >&2
  exit 1
fi
[[ "$("${KUBECTL[@]}" -n "$NAMESPACE" get job "$JOB_NAME" -o json | jq -r '.status.succeeded // 0')" == 1 ]] || { echo "ERROR: Job has no successful Pod" >&2; exit 1; }
pass "running Pod retrieved the immutable manifest with mounted CA and Secret"
echo "  BOUNDARY: kubelet pull from this registry is NOT proven by this Job"

cat > "${RUN_RESULTS_DIR}/results.env" <<EOF
image=https://${REGISTRY_HOST}/${REPOSITORY}@${IMAGE_DIGEST}
image_push_pull=PASS
helm_push_pull=PASS
pull_by_digest=PASS
referrers_sbom=PASS
puller_read_only=PASS
metrics=PASS
in_cluster_client_contract=PASS
kubelet_registry_pull=UNPROVEN
result=PASS
EOF
echo
echo "Phase-2 smoke contract: PASS"
echo "Evidence: $RUN_RESULTS_DIR"
