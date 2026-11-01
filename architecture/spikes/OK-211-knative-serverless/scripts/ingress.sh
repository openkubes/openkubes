#!/usr/bin/env bash
#
# OK-211 — N2: Traefik as the single entry point (ADR-Platform-010 profile v1)
# in front of Kourier (BRIEF B9 Phase 7).
#
# Usage: scripts/ingress.sh render|install|kourier-clusterip|route|test|n2b|n2b-restore|restore
#   render             verify the chart tgz against versions.env, helm template with
#                      ingress/traefik-values.yaml into .local/traefik-rendered.yaml; refuse
#                      if it contains a Secret (BRIEF C7); list the kinds
#   install            namespace ingress, server-side apply of the rendered chart
#                      (field manager traefik-chart), wait Available
#   kourier-clusterip  patch the kourier Service to ClusterIP, mark .local/n2-active
#   route              Ingress knative-via-ok-ingress in kourier-system (ok-ingress -> kourier:80)
#   test               from ok211-probe: http://<node InternalIP>:30080 with the Host header
#   n2b / n2b-restore  domain-template {{.Name}}-{{.Namespace}}.{{.Domain}} with a
#                      *.ok211.internal Ingress, and back (key removed from config-network)
#   restore            route removed, kourier back to LoadBalancer, n2-active removed
#                      (Traefik stays installed)
# The caller (make) runs the guard with --node first and exports HELM_* into .local/.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
ok211::load_versions

K="${KUBECTL:-$SPIKE_ROOT/.local/bin/kubectl}"
RAW="$SPIKE_ROOT/evidence/raw"
CHART="$SPIKE_ROOT/.local/charts/traefik-$TRAEFIK_CHART_VERSION.tgz"
RENDERED="$SPIKE_ROOT/.local/traefik-rendered.yaml"

apply_own() { "$SCRIPT_DIR/render.sh" "$@" | "$K" apply --server-side --field-manager=ok211 -f - >/dev/null; }
node_ip() { "$K" get node ok-knative-local -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}'; }

# probe_via <url> <host> -> "code time_total"
probe_via() {
  "$K" -n ok211-load exec ok211-probe -- curl -sS -o /dev/null --max-time 60 -w '%{http_code} %{time_total}' -H "Host: $2" "$1" || true
}

render() {
  ok211::require_tool helm
  [ -f "$CHART" ] || ok211::die "missing $CHART (download https://traefik.github.io/charts/traefik/traefik-$TRAEFIK_CHART_VERSION.tgz)" 2
  local got; got="$(shasum -a 256 "$CHART" | awk '{print $1}')"
  [ "$got" = "$TRAEFIK_CHART_SHA256" ] || ok211::die "chart checksum $got != TRAEFIK_CHART_SHA256 (STOP-4)" 1
  helm template ok-ingress "$CHART" --namespace ingress \
    -f <("$SCRIPT_DIR/render.sh" "$SPIKE_ROOT/ingress/traefik-values.yaml") > "$RENDERED"
  if yq -N 'select(.kind == "Secret") | .metadata.name' "$RENDERED" | grep -q .; then
    ok211::die "rendered chart contains a Secret (BRIEF C7): $(yq -N 'select(.kind == "Secret") | .metadata.name' "$RENDERED" | tr '\n' ' ')" 1
  fi
  ok211::ok "chart sha256 ok; rendered $(yq -N '.kind' "$RENDERED" | grep -c .) objects, no Secret:"
  yq -N '.kind + "/" + .metadata.name' "$RENDERED" | sort
  echo "image: $(yq -N 'select(.kind == "Deployment") | .spec.template.spec.containers[0].image' "$RENDERED")"
  echo "args:"; yq -N 'select(.kind == "Deployment") | .spec.template.spec.containers[0].args[]' "$RENDERED" | grep -iE 'ingress|entrypoints|provider' || true
}

install() {
  render >/dev/null
  printf 'apiVersion: v1\nkind: Namespace\nmetadata:\n  name: ingress\n  labels:\n    app.kubernetes.io/part-of: ok211\n' \
    | "$K" apply --server-side --field-manager=ok211 -f - >/dev/null
  "$K" apply --server-side --field-manager=traefik-chart -f "$RENDERED" >/dev/null
  "$K" -n ingress wait --for=condition=Available deploy --all --timeout=600s >/dev/null
  ok211::ok "Traefik $TRAEFIK_APP_VERSION installed in namespace ingress"
  "$K" -n ingress get deploy,svc -o wide
  "$K" get ingressclass
}

kourier_clusterip() {
  "$K" -n kourier-system patch service kourier --type merge --patch-file "$SPIKE_ROOT/knative/patch-kourier-clusterip.yaml" >/dev/null
  ok211::touch_private "$SPIKE_ROOT/.local/n2-active"
  ok211::ok "kourier Service is ClusterIP; .local/n2-active set"
  "$K" -n kourier-system get svc kourier -o wide
  "$K" get svc -A --field-selector spec.type=LoadBalancer
}

route() {
  apply_own ingress/kourier-ingress.yaml
  "$K" -n kourier-system get ingress knative-via-ok-ingress -o wide
}

test_n2() {
  local ip out host r_warm r_direct
  ip="$(node_ip)"; out="$RAW/n2-entry-point-$(ok211::stamp).txt"
  host="podinfo.ok211-serving.$KNATIVE_DOMAIN"
  r_warm="$(probe_via "http://$ip:30080/" "$host")"
  r_direct="$(probe_via http://kourier.kourier-system.svc.cluster.local/ "$host")"
  {
    echo "# N2 $(ok211::timestamp)"
    echo "## entry points"; "$K" get svc -A -o wide | grep -E 'NAME|LoadBalancer|NodePort|kourier'
    echo "## svclb pods (ServiceLB)"; "$K" -n kube-system get pods -l svccontroller.k3s.cattle.io/svcname -o wide 2>&1
    echo "## ingress"; "$K" get ingress -A -o wide
    echo "## via Traefik http://$ip:30080 Host: $host -> code time_total"; echo "$r_warm"
    echo "## direct kourier (ClusterIP) -> code time_total"; echo "$r_direct"
    echo "## unknown host via Traefik (expect 404 from Traefik)"; probe_via "http://$ip:30080/" "nope.example.internal"
  } > "$out"
  cat "$out"
}

n2b() {
  local ip out r_new r_old
  "$K" -n knative-serving patch configmap config-network --type merge \
    -p '{"data":{"domain-template":"{{.Name}}-{{.Namespace}}.{{.Domain}}"}}' >/dev/null
  apply_own ingress/kourier-ingress-n2b.yaml
  sleep 15
  ip="$(node_ip)"; out="$RAW/n2b-domain-template-$(ok211::stamp).txt"
  r_new="$(probe_via "http://$ip:30080/" "podinfo-ok211-serving.$KNATIVE_DOMAIN")"
  r_old="$(probe_via "http://$ip:30080/" "podinfo.ok211-serving.$KNATIVE_DOMAIN")"
  {
    echo "# N2b $(ok211::timestamp)"
    echo "## config-network domain-template: $("$K" -n knative-serving get cm config-network -o jsonpath='{.data.domain-template}')"
    echo "## ksvc URLs"; "$K" get ksvc -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,URL:.status.url
    echo "## via Traefik, new host podinfo-ok211-serving.$KNATIVE_DOMAIN -> code time_total"; echo "$r_new"
    echo "## via Traefik, old host podinfo.ok211-serving.$KNATIVE_DOMAIN -> code time_total"; echo "$r_old"
  } > "$out"
  cat "$out"
}

n2b_restore() {
  "$K" -n knative-serving patch configmap config-network --type merge -p '{"data":{"domain-template":null}}' >/dev/null
  "$K" -n kourier-system delete ingress knative-via-ok-ingress-n2b --ignore-not-found >/dev/null
  sleep 15
  echo "domain-template now: '$("$K" -n knative-serving get cm config-network -o jsonpath='{.data.domain-template}')' (empty = release default)"
  "$K" get ksvc -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,URL:.status.url
  echo "old host via Traefik: $(probe_via "http://$(node_ip):30080/" "podinfo.ok211-serving.$KNATIVE_DOMAIN")"
}

restore() {
  "$K" -n kourier-system delete ingress knative-via-ok-ingress knative-via-ok-ingress-n2b --ignore-not-found >/dev/null
  "$K" -n kourier-system patch service kourier --type merge --patch-file "$SPIKE_ROOT/knative/patch-kourier-loadbalancer.yaml" >/dev/null
  rm -f "$SPIKE_ROOT/.local/n2-active"
  ok211::ok "N2 restored: kourier LoadBalancer again, route removed (Traefik stays installed)"
  "$K" -n kourier-system get svc kourier -o wide
}

case "${1:-}" in
  render) render ;;
  install) install ;;
  kourier-clusterip) kourier_clusterip ;;
  route) route ;;
  test) test_n2 ;;
  n2b) n2b ;;
  n2b-restore) n2b_restore ;;
  restore) restore ;;
  *) ok211::die "usage: $0 render|install|kourier-clusterip|route|test|n2b|n2b-restore|restore" 2 ;;
esac
