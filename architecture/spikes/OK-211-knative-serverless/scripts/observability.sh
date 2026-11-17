#!/usr/bin/env bash
#
# OK-211 — X5: which metrics Knative exposes (BRIEF B9 Phase 8).
#
# 1. config-observability of Serving and Eventing as configured (release: no
#    overrides; metrics-protocol defaults to none).
# 2. Scrape /metrics on the ports named in the pod specs (activator,
#    autoscaler, controller, queue-proxy of a fresh podinfo pod, eventing
#    controller/broker ingress/filter) from ok211-probe: before and after
#    setting metrics-protocol / request-metrics-protocol to prometheus.
# 3. Restore: the keys are removed again (release default).
# Results: evidence/raw/x5-observability-<stamp>.json (metric names per
# endpoint, no values) and one JSON line in measurements.json.
# The caller (make) runs the guard with --node first.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
ok211::load_versions
K="${KUBECTL:-$SPIKE_ROOT/.local/bin/kubectl}"
RAW="$SPIKE_ROOT/evidence/raw"
out="$RAW/x5-observability-$(ok211::stamp).json"
tmp="$SPIKE_ROOT/.local/tmp/x5-$(ok211::stamp)"; mkdir -p "$tmp"

# targets -> TSV: label, pod IP, port name, port
targets() {
  local ns d ns_d
  for ns_d in knative-serving/activator knative-serving/autoscaler knative-serving/controller \
              knative-eventing/eventing-controller knative-eventing/mt-broker-ingress knative-eventing/mt-broker-filter; do
    ns="${ns_d%/*}"; d="${ns_d#*/}"
    local sel
    sel="$("$K" -n "$ns" get deploy "$d" -o json | jq -r '.spec.selector.matchLabels | to_entries | map("\(.key)=\(.value)") | join(",")')"
    # shellcheck disable=SC2016  # jq program
    "$K" -n "$ns" get pods -l "$sel" -o json 2>/dev/null \
      | jq -r --arg d "$d" '[.items[] | select(.status.phase == "Running")][0] // empty | .status.podIP as $ip
          | .spec.containers[0].ports[]? | select(.name | test("metric")) | [$d, $ip, .name, (.containerPort | tostring)] | @tsv'
  done
  # shellcheck disable=SC2016
  "$K" -n ok211-serving get pods -l serving.knative.dev/service=podinfo -o json \
    | jq -r '[.items[] | select(.status.phase == "Running" and .metadata.deletionTimestamp == null)][0] // empty | .status.podIP as $ip
        | .spec.containers[] | select(.name == "queue-proxy") | .ports[] | select(.name | test("metric")) | ["queue-proxy", $ip, .name, (.containerPort | tostring)] | @tsv'
}

# scrape <label> -> JSON array: per endpoint code, number of metric families, names
scrape() {
  local label="$1" f="$tmp/$1.tsv"
  # a fresh podinfo pod (its queue-proxy reads config-observability at start)
  "$K" -n ok211-load exec ok211-probe -- curl -sS -o /dev/null --max-time 60 -H "Host: podinfo.ok211-serving.$KNATIVE_DOMAIN" \
    http://kourier.kourier-system.svc.cluster.local/ >/dev/null 2>&1 || true
  targets > "$f"
  while IFS=$'\t' read -r name ip pname port; do
    [ -n "$name" ] || continue
    local body code
    # shellcheck disable=SC2016  # expanded inside the probe pod
    body="$("$K" -n ok211-load exec ok211-probe -- sh -c 'curl -sS --max-time 10 -w "\nHTTPCODE=%{http_code}" "http://$1:$2/metrics" 2>&1 || true' _ "$ip" "$port")"
    code="$(printf '%s' "$body" | sed -n 's/^HTTPCODE=//p' | tail -1)"
    printf '%s' "$body" | grep -E '^# TYPE ' | awk '{print $3}' | sort -u > "$tmp/$label-$name-$port.names" || true
    jq -cn --arg n "$name" --arg pn "$pname" --arg p "$port" --arg c "${code:-000}" --rawfile names "$tmp/$label-$name-$port.names" \
      --arg err "$(printf '%s' "$body" | grep -m1 -E '^curl:' || true)" \
      '{component: $n, port_name: $pn, port: ($p | tonumber), http_code: $c, metric_families: ($names | split("\n") | map(select(length > 0)) | length),
        names: ($names | split("\n") | map(select(length > 0))), curl_error: (if $err == "" then null else $err end)}'
  done < "$f" | jq -s -c .
}

cfg() { for ns in knative-serving knative-eventing; do "$K" -n "$ns" get cm config-observability -o json | jq -c --arg ns "$ns" '{namespace: $ns, overrides: (.data | del(._example))}'; done | jq -s -c .; }

cfg_before="$(cfg)"
before="$(scrape before)"
"$K" -n knative-serving patch configmap config-observability --type merge \
  -p '{"data":{"metrics-protocol":"prometheus","request-metrics-protocol":"prometheus"}}' >/dev/null
"$K" -n knative-eventing patch configmap config-observability --type merge -p '{"data":{"metrics-protocol":"prometheus"}}' >/dev/null
restart_all() {
  "$K" -n knative-serving rollout restart deploy/activator deploy/autoscaler deploy/controller >/dev/null
  "$K" -n knative-eventing rollout restart deploy/eventing-controller deploy/mt-broker-ingress deploy/mt-broker-filter >/dev/null
  "$K" -n knative-serving rollout status deploy/activator deploy/autoscaler deploy/controller --timeout=300s >/dev/null 2>&1 || true
  for d in activator autoscaler controller; do "$K" -n knative-serving rollout status "deploy/$d" --timeout=300s >/dev/null; done
  for d in eventing-controller mt-broker-ingress mt-broker-filter; do "$K" -n knative-eventing rollout status "deploy/$d" --timeout=300s >/dev/null; done
}
# RESTART=1: restart the components after the patch (and after the restore), to
# see whether they pick up the protocol only at start.
[ "${RESTART:-0}" = 1 ] && restart_all
# The podinfo pod must be new: wait until podinfo is at zero.
for _ in $(seq 1 60); do
  [ "$("$K" -n ok211-serving get pods -l serving.knative.dev/service=podinfo -o json | jq '.items | length')" = 0 ] && break
  sleep 3
done
sleep 20
cfg_after="$(cfg)"
after="$(scrape after)"
qp_env="$("$K" -n ok211-serving get pods -l serving.knative.dev/service=podinfo -o json | jq -c '[.items[0].spec.containers[] | select(.name=="queue-proxy") | .env[] | select(.name=="OBSERVABILITY_CONFIG") | .value][0] // null')"
"$K" -n knative-serving patch configmap config-observability --type merge -p '{"data":{"metrics-protocol":null,"request-metrics-protocol":null}}' >/dev/null
"$K" -n knative-eventing patch configmap config-observability --type merge -p '{"data":{"metrics-protocol":null}}' >/dev/null
[ "${RESTART:-0}" = 1 ] && restart_all
cfg_restored="$(cfg)"
jq -n --argjson cb "$cfg_before" --argjson ca "$cfg_after" --argjson cr "$cfg_restored" --argjson b "$before" --argjson a "$after" \
  --argjson qp "$qp_env" --arg ts "$(ok211::timestamp)" \
  --arg restart "${RESTART:-0}" '{id: "X5", restart_components: ($restart == "1"), timestamp_utc: $ts, config_before: $cb, config_during: $ca, config_restored: $cr,
    queue_proxy_observability_env_during: $qp, scrape_before: $b, scrape_during: $a}' > "$out"
jq -c '{id: (if .restart_components then "X5-restart" else .id end), timestamp_utc, knative_version: "1.24.0", config: {during: .config_during, restart_components}, runs: [],
    stats: {before: [.scrape_before[] | {component, port, http_code, metric_families}], during: [.scrape_during[] | {component, port, http_code, metric_families}]},
    notes: "metric names per endpoint in raw; no values recorded", raw: ["'"${out#"$SPIKE_ROOT/"}"'"]}' "$out" >> "$RAW/measurements.json"
rm -rf "$tmp"
jq '{config_before, config_restored, queue_proxy_observability_env_during,
     before: [.scrape_before[] | {component, port_name, port, http_code, metric_families, curl_error}],
     during: [.scrape_during[] | {component, port_name, port, http_code, metric_families, sample: .names[0:8]}]}' "$out"
