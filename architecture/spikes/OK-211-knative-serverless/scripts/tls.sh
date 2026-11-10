#!/usr/bin/env bash
#
# OK-211 — N3: TLS for external Knative domains with cert-manager (BRIEF B9 Phase 7).
#
# Usage: scripts/tls.sh install|enable|test|disable
#   install  cert-manager from .local/manifests/cert-manager/cert-manager.yaml (sha256
#            checked against versions.env), server-side (field manager cert-manager-release);
#            then tls/issuers.yaml (self-signed root CA, CA ClusterIssuer)
#   enable   config-certmanager issuerRef, config-network external-domain-tls: Enabled
#            (merge patches), restart the serving controller as the docs say, wait for https URLs
#   test     Job in namespace cert-manager that mounts only ca.crt of the CA secret
#            (items: [{key: ca.crt, path: ca.crt}]; tls.key is never mounted or read):
#            curl --connect-to <host>:443:kourier…:443 --cacert …  -> expect 200;
#            the same without --cacert -> expect exit 60; and through Traefik websecure
#            (NodePort 30443) with --cacert, to see which certificate the entry point presents
#   disable  external-domain-tls back to Disabled (issuers and cert-manager stay)
# The caller (make) runs the guard with --node first.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
ok211::load_versions

K="${KUBECTL:-$SPIKE_ROOT/.local/bin/kubectl}"
RAW="$SPIKE_ROOT/evidence/raw"
CM_MANIFEST="$SPIKE_ROOT/.local/manifests/cert-manager/cert-manager.yaml"

apply_own() { "$SCRIPT_DIR/render.sh" "$@" | "$K" apply --server-side --field-manager=ok211 -f - >/dev/null; }

install() {
  local got
  [ -f "$CM_MANIFEST" ] || ok211::die "missing $CM_MANIFEST; run 'make manifests-fetch VERSION=cert-manager'" 2
  got="$(shasum -a 256 "$CM_MANIFEST" | awk '{print $1}')"
  [ "$got" = "$MANIFEST_SHA256_CERT_MANAGER_CERT_MANAGER" ] || ok211::die "cert-manager.yaml sha256 $got != pin (STOP-4)" 1
  "$K" apply --server-side --field-manager=cert-manager-release -f "$CM_MANIFEST" >/dev/null
  "$K" wait --for=condition=Established --timeout=300s crd/certificates.cert-manager.io crd/clusterissuers.cert-manager.io >/dev/null
  "$K" -n cert-manager wait --for=condition=Available deploy --all --timeout=600s >/dev/null
  # The webhook must answer before cert-manager objects can be created.
  for _ in $(seq 1 60); do
    apply_own tls/issuers.yaml 2>/dev/null && break
    sleep 2
  done
  apply_own tls/issuers.yaml
  "$K" -n cert-manager wait --for=condition=Ready certificate/ok211-ca --timeout=300s >/dev/null
  "$K" wait --for=condition=Ready clusterissuer/ok211-ca-issuer --timeout=300s >/dev/null
  ok211::ok "cert-manager $CERT_MANAGER_VERSION installed; ClusterIssuer ok211-ca-issuer Ready"
  "$K" -n cert-manager get deploy -o wide
  "$K" -n cert-manager get pods -o json | jq -r '.items[].status.containerStatuses[] | "\(.name) \(.imageID)"'
  "$K" get clusterissuers
}

enable() {
  "$K" -n knative-serving patch configmap config-certmanager --type merge --patch-file "$SPIKE_ROOT/knative/patch-config-certmanager.yaml" >/dev/null
  "$K" -n knative-serving patch configmap config-network --type merge --patch-file "$SPIKE_ROOT/knative/patch-config-network-tls.yaml" >/dev/null
  "$K" -n knative-serving rollout restart deploy/controller >/dev/null
  "$K" -n knative-serving rollout status deploy/controller --timeout=300s >/dev/null
  local i url
  for i in $(seq 1 90); do
    url="$("$K" -n ok211-serving get ksvc podinfo -o jsonpath='{.status.url}')"
    case "$url" in https://*) break ;; esac
    sleep 2
  done
  ok211::ok "after $((i * 2)) s: podinfo URL $url"
  "$K" -n ok211-serving get certificates.networking.internal.knative.dev,certificates.cert-manager.io -o wide 2>&1
  "$K" get ksvc -A -o json | jq -r '.items[] | [.metadata.namespace, .metadata.name, .status.url, ([.status.conditions[] | select(.type=="Ready") | .status][0])] | @tsv'
}

test_tls() {
  local name out host ip
  name="tls-check-$(date -u +%H%M%S)"; out="$RAW/n3-tls-$(ok211::stamp).txt"
  host="podinfo.ok211-serving.$KNATIVE_DOMAIN"
  ip="$("$K" get node ok-knative-local -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}')"
  # shellcheck disable=SC2016  # runs inside the Job pod
  local script='
echo "== 1 kourier with --cacert (expect 200, verify ok)"
curl -sS -v -o /dev/null -w "code=%{http_code} ssl_verify=%{ssl_verify_result} time=%{time_total}\n" --max-time 60 \
  --connect-to "$HOST:443:kourier.kourier-system.svc.cluster.local:443" --cacert /ca/ca.crt "https://$HOST/" 2>&1 \
  | grep -E "code=|subject:|issuer:|SSL certificate verify|expire date|start date|subjectAltName|TLSv1|ALPN" ; echo "exit=$?"
echo "== 2 kourier without --cacert (expect curl exit 60)"
curl -sS -o /dev/null --max-time 30 --connect-to "$HOST:443:kourier.kourier-system.svc.cluster.local:443" "https://$HOST/"; echo "exit=$?"
echo "== 3 Traefik websecure NodePort 30443 with --cacert (which certificate does the entry point present?)"
curl -sS -v -o /dev/null -w "code=%{http_code}\n" --max-time 30 --connect-to "$HOST:443:$NODE_IP:30443" --cacert /ca/ca.crt "https://$HOST/" 2>&1 \
  | grep -E "code=|subject:|issuer:|SSL certificate|curl: \(" ; echo "exit=$?"
echo "== 4 plain http through kourier after enabling TLS"
curl -sS -o /dev/null -w "code=%{http_code}\n" --max-time 30 -H "Host: $HOST" http://kourier.kourier-system.svc.cluster.local/; echo "exit=$?"'
  jq -n --arg name "$name" --arg img "$CURL_IMAGE" --arg script "$script" --arg host "$host" --arg ip "$ip" '{
    apiVersion: "batch/v1", kind: "Job",
    metadata: {name: $name, namespace: "cert-manager", labels: {"app.kubernetes.io/part-of": "ok211"}},
    spec: {backoffLimit: 0, ttlSecondsAfterFinished: 3600, template: {spec: {
      restartPolicy: "Never", automountServiceAccountToken: false,
      securityContext: {runAsNonRoot: true, runAsUser: 100, runAsGroup: 101, seccompProfile: {type: "RuntimeDefault"}},
      volumes: [{name: "ca", secret: {secretName: "ok211-ca", items: [{key: "ca.crt", path: "ca.crt"}]}}],
      containers: [{name: "check", image: $img, command: ["sh", "-c", $script],
        env: [{name: "HOST", value: $host}, {name: "NODE_IP", value: $ip}],
        volumeMounts: [{name: "ca", mountPath: "/ca", readOnly: true}],
        securityContext: {allowPrivilegeEscalation: false, readOnlyRootFilesystem: true, capabilities: {drop: ["ALL"]}},
        resources: {requests: {cpu: "10m", memory: "16Mi"}, limits: {cpu: "500m", memory: "64Mi"}}}]}}}}' \
    | "$K" create -f - >/dev/null
  "$K" -n cert-manager wait --for=condition=Complete --timeout=300s "job/$name" >/dev/null || true
  {
    echo "# N3 $(ok211::timestamp)"
    echo "## config-network external-domain-tls: $("$K" -n knative-serving get cm config-network -o jsonpath='{.data.external-domain-tls}')"
    echo "## config-certmanager issuerRef:"; "$K" -n knative-serving get cm config-certmanager -o jsonpath='{.data.issuerRef}'; echo
    echo "## ksvc podinfo URL: $("$K" -n ok211-serving get ksvc podinfo -o jsonpath='{.status.url}')"
    echo "## Knative certificate / cert-manager certificate"
    "$K" -n ok211-serving get certificates.networking.internal.knative.dev,certificates.cert-manager.io -o wide 2>&1
    echo "## job $name (mounts only ca.crt)"
    "$K" -n cert-manager get job "$name" -o json | jq -c '.spec.template.spec.volumes'
    "$K" -n cert-manager logs "job/$name"
  } > "$out"
  cat "$out"
}

disable() {
  "$K" -n knative-serving patch configmap config-network --type merge --patch-file "$SPIKE_ROOT/knative/patch-config-network-tls-off.yaml" >/dev/null
  "$K" -n knative-serving rollout restart deploy/controller >/dev/null
  "$K" -n knative-serving rollout status deploy/controller --timeout=300s >/dev/null
  sleep 10
  "$K" get ksvc -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,URL:.status.url
}

case "${1:-}" in
  install) install ;;
  enable) enable ;;
  test) test_tls ;;
  disable) disable ;;
  *) ok211::die "usage: $0 install|enable|test|disable" 2 ;;
esac
