#!/usr/bin/env bash
#
# OK-211 — networking experiments N1 and N4 (BRIEF B9 Phase 7). N2 and N3
# have their own scripts (ingress.sh, tls.sh).
#
# Usage: scripts/measure-networking.sh n1|n4
#   n1  Kourier's LoadBalancer through K3s ServiceLB: svclb pods, host ports,
#       NodePorts; a second LoadBalancer on 80/443 stays Pending; removed again.
#   n4  ksvc podinfo-private with the label visibility=cluster-local: external
#       host through kourier -> 404, cluster-local name through kourier-internal -> 200.
# The caller (make) runs the guard with --node first.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
ok211::load_versions

K="${KUBECTL:-$SPIKE_ROOT/.local/bin/kubectl}"
RAW="$SPIKE_ROOT/evidence/raw"

apply_own() { "$SCRIPT_DIR/render.sh" "$@" | "$K" apply --server-side --field-manager=ok211 -f - >/dev/null; }

probe() { "$K" -n ok211-load exec ok211-probe -- "$@"; }

n1() {
  local out st phase ev
  out="$RAW/n1-servicelb-$(ok211::stamp).txt"
  {
    echo "# N1 $(ok211::timestamp)"
    echo "## LoadBalancer services"; "$K" get svc -A --field-selector spec.type=LoadBalancer -o wide
    echo "## kourier service ports (port:nodePort)"
    "$K" -n kourier-system get svc kourier -o json | jq -r '.spec.ports[] | "\(.name) \(.port) -> nodePort \(.nodePort), targetPort \(.targetPort)"'
    echo "## svclb pods in kube-system"; "$K" -n kube-system get pods -l svccontroller.k3s.cattle.io/svcname -o wide
    echo "## svclb hostPorts"
    "$K" -n kube-system get pods -l svccontroller.k3s.cattle.io/svcname -o json \
      | jq -r '.items[] | .metadata.name as $p | .spec.containers[] | "\($p) \(.name) hostPort=\([.ports[]?.hostPort] | join(","))"'
  } > "$out"
  apply_own ingress/n1-second-lb.yaml
  sleep 20
  phase="$("$K" -n ok211-serving get svc ok211-n1-second-lb -o json | jq -c '{ingress: .status.loadBalancer.ingress, type: .spec.type}')"
  ev="$("$K" -n ok211-serving get events --field-selector involvedObject.name=ok211-n1-second-lb -o json | jq -r '.items[] | "\(.lastTimestamp) \(.reason) \(.message)"')"
  {
    echo "## second LoadBalancer ok211-n1-second-lb after 20 s"; echo "$phase"
    "$K" -n ok211-serving get svc ok211-n1-second-lb -o wide
    echo "## its svclb pods"
    "$K" -n kube-system get pods -l svccontroller.k3s.cattle.io/svcname=ok211-n1-second-lb -o wide 2>&1
    "$K" -n kube-system get pods -l svccontroller.k3s.cattle.io/svcname=ok211-n1-second-lb -o json \
      | jq -r '.items[] | "\(.metadata.name) phase=\(.status.phase) \([.status.conditions[]? | select(.type=="PodScheduled") | "\(.reason // "") \(.message // "")"] | join(" "))"'
    echo "## events"; echo "$ev"
  } >> "$out"
  "$K" -n ok211-serving delete svc ok211-n1-second-lb --wait=true >/dev/null
  echo "## removed again at $(ok211::timestamp)" >> "$out"
  st="$(jq -cn --argjson p "$phase" '{second_lb_external_ip: ($p.ingress // null), pending: (($p.ingress // []) | length == 0)}')"
  jq -cn --arg ts "$(ok211::timestamp)" --argjson st "$st" --arg raw "${out#"$SPIKE_ROOT/"}" \
    '{id: "N1", timestamp_utc: $ts, knative_version: "1.24.0", config: {kourier_service: "LoadBalancer (release default)", servicelb: "k3s klipper-lb"}, runs: [], stats: $st, notes: "second LoadBalancer Service on 80/443 in ok211-serving, observed 20 s, then deleted", raw: [$raw]}' \
    >> "$RAW/measurements.json"
  cat "$out"
}

n4() {
  local out ext loc ksvc_url
  out="$RAW/n4-cluster-local-$(ok211::stamp).txt"
  apply_own apps/serving/podinfo-private.yaml
  "$K" -n ok211-serving wait --for=condition=Ready ksvc/podinfo-private --timeout=300s >/dev/null
  ksvc_url="$("$K" -n ok211-serving get ksvc podinfo-private -o jsonpath='{.status.url}')"
  ext="$(probe curl -sS -o /dev/null --max-time 60 -w '%{http_code} %{time_total}' \
    -H "Host: podinfo-private.ok211-serving.$KNATIVE_DOMAIN" http://kourier.kourier-system.svc.cluster.local/ || true)"
  loc="$(probe curl -sS -o /dev/null --max-time 60 -w '%{http_code} %{time_total}' \
    http://podinfo-private.ok211-serving.svc.cluster.local/ || true)"
  {
    echo "# N4 $(ok211::timestamp)"
    echo "## ksvc labels"; "$K" -n ok211-serving get ksvc podinfo-private -o json | jq -c '.metadata.labels'
    echo "## status.url: $ksvc_url"
    echo "## route visibility / kingress"
    "$K" -n ok211-serving get ingresses.networking.internal.knative.dev podinfo-private -o json \
      | jq -c '{rules: [.spec.rules[] | {hosts, visibility}]}'
    echo "## service podinfo-private (ExternalName to kourier-internal?)"
    "$K" -n ok211-serving get svc podinfo-private -o wide
    echo "## external host via kourier: code time_total"; echo "$ext"
    echo "## http://podinfo-private.ok211-serving.svc.cluster.local/: code time_total"; echo "$loc"
  } > "$out"
  jq -cn --arg ts "$(ok211::timestamp)" --arg ext "$ext" --arg loc "$loc" --arg url "$ksvc_url" --arg raw "${out#"$SPIKE_ROOT/"}" \
    '{id: "N4", timestamp_utc: $ts, knative_version: "1.24.0", config: {label: "networking.knative.dev/visibility=cluster-local"}, runs: [],
      stats: {status_url: $url, external_via_kourier: ($ext | split(" ") | {code: .[0], total_s: (.[1] | tonumber? )}),
              cluster_local: ($loc | split(" ") | {code: .[0], total_s: (.[1] | tonumber?)})},
      notes: "first request may include a cold start", raw: [$raw]}' >> "$RAW/measurements.json"
  cat "$out"
}

case "${1:-}" in
  n1) n1 ;;
  n4) n4 ;;
  *) ok211::die "usage: $0 n1|n4" 2 ;;
esac
