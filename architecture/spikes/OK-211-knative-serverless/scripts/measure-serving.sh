#!/usr/bin/env bash
#
# OK-211 — Serving measurements S1-S10 (BRIEF B9 Phase 5, B11).
#
# Usage: scripts/measure-serving.sh <cmd> [args]
#   s1                         objects of ksvc podinfo, 200 through Kourier
#   s2 [runs]                  scale-to-zero time of podinfo with default config (3 runs)
#   coldstart <id> <ksvc> <n>  cold start: from 0 pods (B11 state check), one request, n runs
#                              (S3: podinfo, S4: podinfo with image removed, S7: podinfo-min1)
#   fortio <id> <ksvc> <qps> <conns> <n|duration>   fortio Job in ok211-load, JSON result
#   s6                         autoscaling of podinfo-scale: fortio 50 conns 60 s, pods every 2 s
#   s8                         revisions, 80/20 split, tag route, rollback (podinfo-split)
#   s9                         timeout: podinfo-timeout, /delay/30 with timeoutSeconds 20
#   s10 [samples] [interval]   resource overhead per namespace and queue-proxy per pod
#   config <ksvc>              configuration record (config-autoscaler, config-defaults, annotations)
#
# Every measurement runs inside the cluster: curl in ok211-probe or a fortio Job.
# Results: one JSON line per series in evidence/raw/measurements.json; raw data in
# evidence/raw/<id>-<stamp>.*. Kubernetes condition timestamps have 1 s
# resolution, so any breakdown of a cold start is coarse and marked as such.
# The caller (make) runs the guard with --node first.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
ok211::load_versions

K="${KUBECTL:-$SPIKE_ROOT/.local/bin/kubectl}"
RAW="$SPIKE_ROOT/evidence/raw"
NS=ok211-serving
KOURIER=http://kourier.kourier-system.svc.cluster.local
MAX_TIME=120

# shellcheck disable=SC2016  # jq programs
JQ_STATS='
def nr($p): sort | if length == 0 then null else .[((length*$p/100)|ceil) - 1 | if . < 0 then 0 else . end] end;
def stats: if length == 0 then {n: 0}
  elif length < 10 then {n: length, min: min, median: nr(50), max: max}
  else {n: length, min: min, median: nr(50), p90: nr(90), max: max} end;
'

host() { printf '%s.%s.%s' "$1" "$NS" "$KNATIVE_DOMAIN"; }
now_ms() { python3 -c 'import time; print(int(time.time()*1000))'; }

# probe_curl <ksvc> [path] -> "<vm_epoch_s> <code> <connect_s> <starttransfer_s> <total_s> <curl_exit>"
probe_curl() {
  local h; h="$(host "$1")"
  # shellcheck disable=SC2016  # expanded inside the probe pod
  "$K" -n ok211-load exec ok211-probe -- sh -c '
    t=$(date -u +%s)
    r=$(curl -sS -o /dev/null --max-time "$3" -H "Host: $1" -w "%{http_code} %{time_connect} %{time_starttransfer} %{time_total}" "$2" 2>/dev/null); rc=$?
    echo "$t ${r:-000 0 0 0} $rc"' _ "$h" "$KOURIER${2:-/}" "$MAX_TIME"
}

latest_rev() { "$K" -n "$NS" get ksvc "$1" -o jsonpath='{.status.latestReadyRevisionName}'; }

# rev_pods <rev>: number of pods of the revision, including Terminating ones.
rev_pods() {
  "$K" -n "$NS" get pods -l "serving.knative.dev/revision=$1" -o json | jq '.items | length'
}

# zero_state <rev> -> "pods actualScale sksMode"
zero_state() {
  local p a m
  p="$(rev_pods "$1")"
  a="$("$K" -n "$NS" get podautoscaler "$1" -o jsonpath='{.status.actualScale}')"
  m="$("$K" -n "$NS" get sks "$1" -o jsonpath='{.spec.mode}')"
  printf '%s %s %s\n' "$p" "${a:-?}" "${m:-?}"
}

# wait_zero <rev> <timeout_s>: B11 state before a cold start: no pods (not even
# Terminating), PodAutoscaler actualScale 0, SKS mode Proxy. Then 10 s.
wait_zero() {
  local rev="$1" t="$2" s i=0
  while :; do
    s="$(zero_state "$rev")"
    [ "$s" = "0 0 Proxy" ] && break
    i=$((i + 2)); [ "$i" -lt "$t" ] || ok211::die "revision $rev not at zero after ${t}s (pods/actualScale/sks: $s)" 1
    sleep 2
  done
  sleep 10
}

config_json() { # config_json <ksvc>
  local ver ann
  ver="$("$K" -n knative-serving get deploy controller -o jsonpath='{.metadata.labels.app\.kubernetes\.io/version}')"
  ann="$("$K" -n "$NS" get ksvc "$1" -o json | jq -c '{service: (.metadata.annotations // {} | with_entries(select(.key | test("autoscaling|serving.knative.dev/rollout")))),
      template: (.spec.template.metadata.annotations // {}), containerConcurrency: .spec.template.spec.containerConcurrency,
      timeoutSeconds: .spec.template.spec.timeoutSeconds, image: .spec.template.spec.containers[0].image}')"
  jq -cn --arg v "$ver" --arg ksvc "$1" --argjson ann "$ann" \
    --argjson as "$("$K" -n knative-serving get cm config-autoscaler -o json | jq -c '.data | del(._example)')" \
    --argjson df "$("$K" -n knative-serving get cm config-defaults -o json | jq -c '.data | del(._example)')" \
    '{knative_version: $v, ksvc: $ksvc, ksvc_spec: $ann,
      config_autoscaler_overrides: $as, config_defaults_overrides: $df,
      note: "empty overrides = release defaults (stable-window 60s, scale-to-zero-grace-period 30s, scale-to-zero-pod-retention-period 0s, container-concurrency-target-percentage 70, panic-window-percentage 10, panic-threshold-percentage 200, revision-timeout-seconds 300, max-revision-timeout-seconds 600)"}'
}

record() { # record <id> <config json> <runs json> <stats json> <notes> [raw files...]
  local id="$1" cfg="$2" runs="$3" st="$4" notes="$5"; shift 5
  local raw; raw="$(printf '%s\n' "$@" | jq -R . | jq -s -c 'map(select(length > 0))')"
  jq -cn --arg id "$id" --arg ts "$(ok211::timestamp)" --argjson cfg "$cfg" --argjson runs "$runs" \
    --argjson st "$st" --arg notes "$notes" --argjson raw "$raw" \
    '{id: $id, timestamp_utc: $ts, knative_version: $cfg.knative_version, config: $cfg, runs: $runs, stats: $st, notes: $notes, raw: $raw}' \
    >> "$RAW/measurements.json"
}

# ---------------------------------------------------------------------------
s1() {
  local rev out r
  out="$RAW/s1-objects-$(ok211::stamp).txt"
  rev="$(latest_rev podinfo)"
  {
    echo "# ksvc podinfo, revision $rev ($(ok211::timestamp))"
    for k in ksvc configuration revision route podautoscaler sks ingresses.networking.internal.knative.dev; do
      echo "## $k"; "$K" -n "$NS" get "$k" -o wide 2>&1
    done
    echo "## ownerReferences"
    for k in configuration/podinfo "revision/$rev" route/podinfo "podautoscaler/$rev" "sks/$rev" ingresses.networking.internal.knative.dev/podinfo; do
      "$K" -n "$NS" get "$k" -o json | jq -r '"\(.kind)/\(.metadata.name) <- \([.metadata.ownerReferences[]? | "\(.kind)/\(.name)"] | join(","))"'
    done
  } > "$out"
  r="$(probe_curl podinfo)"
  echo "## request: vm_epoch code connect starttransfer total exit" >> "$out"; echo "$r" >> "$out"
  cat "$out"
}

# ---------------------------------------------------------------------------
# S2: generate some traffic, then measure from the end of the last request to
# (a) PodAutoscaler desired 0, (b) pod deletionTimestamp, (c) no pod left.
s2() {
  local runs_n="${1:-3}" rev i r last_vm last_mac t ds dz cfg out runs="[]" del_ts
  rev="$(latest_rev podinfo)"; cfg="$(config_json podinfo)"
  out="$RAW/s2-scale-to-zero-$(ok211::stamp).tsv"
  printf 'run\tlast_request_vm_epoch\tdesired0_after_s\tdeletion_ts_after_s\tno_pod_after_s\n' > "$out"
  for i in $(seq 1 "$runs_n"); do
    ok211::info "S2 run $i/$runs_n: 20 requests to podinfo ($rev)"
    for _ in $(seq 1 20); do r="$(probe_curl podinfo)"; done
    last_vm="$(awk '{print $1}' <<<"$r")"; last_mac="$(now_ms)"
    ds=""; dz=""; del_ts=""
    while :; do
      t="$(now_ms)"
      if [ -z "$ds" ] && [ "$("$K" -n "$NS" get podautoscaler "$rev" -o jsonpath='{.status.desiredScale}')" = "0" ]; then
        ds=$(( t - last_mac )); fi
      if [ -z "$del_ts" ]; then
        del_ts="$("$K" -n "$NS" get pods -l "serving.knative.dev/revision=$rev" -o json \
          | jq -r '[.items[].metadata.deletionTimestamp // empty][0] // empty')"; fi
      if [ "$(rev_pods "$rev")" = "0" ]; then dz=$(( t - last_mac )); break; fi
      [ $(( t - last_mac )) -lt 600000 ] || ok211::die "S2 run $i: still pods after 600 s" 1
      sleep 1
    done
    local del_after="null"
    [ -n "$del_ts" ] && del_after="$(jq -n --arg d "$del_ts" --argjson l "$last_vm" '($d | fromdateiso8601) - $l')"
    printf '%s\t%s\t%s\t%s\t%s\n' "$i" "$last_vm" "$(jq -n "${ds:-null}/1000")" "$del_after" "$(jq -n "$dz/1000")" >> "$out"
    runs="$(jq -c --argjson i "$i" --argjson ds "${ds:-null}" --argjson del "$del_after" --argjson dz "$dz" \
      '. + [{run: $i, desired_zero_after_ms: $ds, deletion_timestamp_after_s: $del, no_pod_after_ms: $dz}]' <<<"$runs")"
    ok211::ok "S2 run $i: desiredScale 0 after $(jq -n "${ds:-null}/1000") s, deletionTimestamp after ${del_after} s, no pod after $(jq -n "$dz/1000") s"
    sleep 5
  done
  record S2 "$cfg" "$runs" "$(jq -c "$JQ_STATS"'{desired_zero_ms: (map(.desired_zero_after_ms) | stats), no_pod_ms: (map(.no_pod_after_ms) | stats), deletion_timestamp_s: (map(.deletion_timestamp_after_s) | stats)}' <<<"$runs")" \
    "time from the end of the last request (Mac clock, polled every 1 s; VM clock skew ≈ 0.2 s) to PodAutoscaler desiredScale 0 and to no pod of the revision left; deletion_timestamp_after_s = pod deletionTimestamp (1 s resolution) minus last request start in the probe (VM clock, 1 s resolution)" \
    "${out#"$SPIKE_ROOT/"}"
  cat "$out"
}

# ---------------------------------------------------------------------------
# coldstart <id> <ksvc> <n>: B11 state check, request, then the pod's
# timeline from its conditions (1 s resolution). For S4 the image of the
# revision is removed from the node before every run (make node-rmi).
coldstart() {
  local id="$1" ksvc="$2" n="$3" rev cfg out runs="[]" i r pod pj img
  rev="$(latest_rev "$ksvc")"; cfg="$(config_json "$ksvc")"
  out="$RAW/$(printf '%s' "$id" | tr '[:upper:]' '[:lower:]')-coldstart-$(ok211::stamp).tsv"
  img="$("$K" -n "$NS" get revision "$rev" -o json | jq -r '.status.containerStatuses[] | select(.name=="podinfo" or .name=="user-container") | .imageDigest' | head -1)"
  printf 'run\tvm_epoch\tcode\tconnect_s\tstarttransfer_s\ttotal_s\tcurl_exit\tpod\tcreated\tscheduled\tuser_started\tqp_started\tready\tpulled_msg\n' > "$out"
  for i in $(seq 1 "$n"); do
    if [ "$id" != "S7" ]; then wait_zero "$rev" 600; fi
    if [ "$id" = "S4" ]; then
      "$SCRIPT_DIR/node-image.sh" rmi "$img" || ok211::die "S4: could not remove $img from the node" 1
    fi
    r="$(probe_curl "$ksvc")"
    pod="$("$K" -n "$NS" get pods -l "serving.knative.dev/revision=$rev" -o json \
      | jq -r '[.items[] | select(.metadata.deletionTimestamp == null)] | sort_by(.metadata.creationTimestamp) | last | .metadata.name // ""')"
    pj="{}"; local pulled=""
    if [ -n "$pod" ]; then
      pj="$("$K" -n "$NS" get pod "$pod" -o json | jq -c '{created: .metadata.creationTimestamp,
          scheduled: ([.status.conditions[] | select(.type=="PodScheduled") | .lastTransitionTime][0]),
          user_started: ([.status.containerStatuses[] | select(.name != "queue-proxy") | .state.running.startedAt][0]),
          qp_started: ([.status.containerStatuses[] | select(.name == "queue-proxy") | .state.running.startedAt][0]),
          ready: ([.status.conditions[] | select(.type=="Ready" and .status=="True") | .lastTransitionTime][0])}')"
      pulled="$("$K" -n "$NS" get events --field-selector "involvedObject.name=$pod,reason=Pulled" -o json \
        | jq -r '[.items[] | select(.message | test("podinfo")) | .message][0] // ""')"
    fi
    printf '%s\t%s\t%s\t%s\t%s\n' "$i" "$(tr ' ' '\t' <<<"$r")" "$pod" \
      "$(jq -r '[.created,.scheduled,.user_started,.qp_started,.ready] | map(. // "-") | join("\t")' <<<"$pj")" "$pulled" >> "$out"
    ok211::ok "$id run $i/$n: $(tail -1 "$out" | awk -F'\t' '{printf "%s total %s s, pod %s", $3, $6, $8}')"
  done
  coldstart_eval "$id" "$out" "$(jq -c --arg img "$img" --arg rev "$rev" '. + {revision: $rev, image_digest: $img}' <<<"$cfg")"
}

# coldstart_eval <id> <tsv> <config json>: runs and stats from the raw TSV,
# appended to measurements.json. Also usable on an existing TSV.
coldstart_eval() {
  local id="$1" tsv="$2" cfg="$3" runs st
  runs="$(jq -R -s -c '
    def rel($x; $t0): if ($x // "-") == "-" then null else (($x | fromdateiso8601) - $t0) end;
    split("\n") | .[1:] | map(select(length > 0) | split("\t")) | map(
      (.[1] | tonumber) as $t0
      | {run: (.[0] | tonumber), code: .[2], curl_exit: (.[6] | tonumber), total_ms: ((.[5] | tonumber) * 1000 | round),
         connect_ms: ((.[3] | tonumber) * 1000 | round), pod: .[7],
         coarse_s_after_request: {created: rel(.[8]; $t0), scheduled: rel(.[9]; $t0), user_container_started: rel(.[10]; $t0),
           queue_proxy_started: rel(.[11]; $t0), ready: rel(.[12]; $t0)},
         pulled_event: (.[13] // "" | if . == "" then null else . end),
         pull_ms: ([(.[13] // "") | capture("Successfully pulled image .* in (?<v>[0-9.]+)(?<u>ms|s) ")][0]
                   | if . == null then null else ((.v | tonumber) * (if .u == "s" then 1000 else 1 end) | round) end)})' "$tsv")"
  st="$(jq -c "$JQ_STATS"'{total_ms: (map(select(.code == "200") | .total_ms) | stats), errors: (map(select(.code != "200" or .curl_exit != 0)) | length),
        pull_ms: (map(.pull_ms // empty) | stats), coarse_ready_s: (map(.coarse_s_after_request.ready // empty) | stats),
        image_cached_runs: (map(select((.pulled_event // "") | test("already present"))) | length)}' <<<"$runs")"
  record "$id" "$cfg" "$runs" "$st" \
    "total_ms = curl time_total in ok211-probe (ms). coarse_s_after_request = Kubernetes timestamps (1 s resolution) minus the request start in the probe (1 s resolution); coarse, as B11 says" \
    "${tsv#"$SPIKE_ROOT/"}"
  jq . <<<"$st"
}

# ---------------------------------------------------------------------------
# fortio <id> <ksvc> <qps> <conns> <n|duration> [path]: fortio load as a Job in
# ok211-load (PSA restricted). Prints the result JSON to stdout.
fortio_run() {
  local id="$1" ksvc="$2" qps="$3" c="$4" amount="$5" path="${6:-/}" name job_json lim
  name="fortio-$(printf '%s' "$id" | tr '[:upper:]' '[:lower:]')-$(date -u +%H%M%S)"
  case "$amount" in *s) lim="-t $amount" ;; *) lim="-n $amount" ;; esac
  # shellcheck disable=SC2086  # $lim is two words on purpose
  job_json="$(jq -n --arg name "$name" --arg img "$FORTIO_IMAGE" --arg host "$(host "$ksvc")" \
    --arg url "$KOURIER$path" --arg qps "$qps" --arg c "$c" --arg lim "$lim" '{
    apiVersion: "batch/v1", kind: "Job",
    metadata: {name: $name, namespace: "ok211-load", labels: {"app.kubernetes.io/part-of": "ok211", "app.kubernetes.io/name": "fortio"}},
    spec: {backoffLimit: 0, ttlSecondsAfterFinished: 3600, template: {
      metadata: {labels: {"app.kubernetes.io/name": "fortio"}},
      spec: {restartPolicy: "Never", automountServiceAccountToken: false,
        securityContext: {runAsNonRoot: true, runAsUser: 65532, runAsGroup: 65532, seccompProfile: {type: "RuntimeDefault"}},
        containers: [{name: "fortio", image: $img,
          args: (["load", "-quiet", "-json", "-", "-qps", $qps, "-c", $c] + ($lim | split(" ")) + ["-timeout", "30s", "-H", ("Host: " + $host), $url]),
          securityContext: {allowPrivilegeEscalation: false, readOnlyRootFilesystem: true, capabilities: {drop: ["ALL"]}},
          resources: {requests: {cpu: "100m", memory: "64Mi"}, limits: {cpu: "2", memory: "256Mi"}}}]}}}}')"
  printf '%s\n' "$job_json" | "$K" create -f - >/dev/null
  "$K" -n ok211-load wait --for=condition=Complete --timeout=600s "job/$name" >/dev/null \
    || { "$K" -n ok211-load logs "job/$name" | tail -20 >&2; ok211::die "fortio job $name did not complete" 1; }
  # kubectl logs mixes stdout and stderr, and fortio's stderr line "Successfully
  # wrote … bytes of Json data" can land inside the JSON. Keep only the JSON
  # (fortio indents every inner line), from the first "{" to the closing "}".
  "$K" -n ok211-load logs "job/$name" | awk '/^\{/{f=1} f && /^(\{|\}|[ \t])/{print} f && /^\}/{exit}' | jq -c .
}

fortio_cmd() { # fortio <id> <ksvc> <qps> <conns> <amount> [warmup]
  local id="$1" ksvc="$2" qps="$3" c="$4" amount="$5" out js cfg st
  cfg="$(config_json "$ksvc")"
  ok211::info "$id: warm-up 30 s (not evaluated)"
  fortio_run "$id-warmup" "$ksvc" "$qps" "$c" 30s > /dev/null
  out="$RAW/$(printf '%s' "$id" | tr '[:upper:]' '[:lower:]')-fortio-$(ok211::stamp).json"
  fortio_run "$id" "$ksvc" "$qps" "$c" "$amount" > "$out"
  js="$(jq -c '{requested_qps: .RequestedQPS, actual_qps: .ActualQPS, connections: .NumThreads, count: .DurationHistogram.Count,
      codes: .RetCodes, min_ms: (.DurationHistogram.Min*1000), avg_ms: (.DurationHistogram.Avg*1000), max_ms: (.DurationHistogram.Max*1000),
      p50_ms: ([.DurationHistogram.Percentiles[] | select(.Percentile==50) | .Value*1000][0]),
      p90_ms: ([.DurationHistogram.Percentiles[] | select(.Percentile==90) | .Value*1000][0]),
      p99_ms: ([.DurationHistogram.Percentiles[] | select(.Percentile==99) | .Value*1000][0])}' "$out")"
  st="$js"
  record "$id" "$(jq -c --arg q "$qps" --arg c "$c" --arg a "$amount" '. + {fortio: {qps: $q, connections: $c, amount: $a, warmup_s: 30}}' <<<"$cfg")" \
    "$(jq -c '[.DurationHistogram.Data[]? | {start_ms: (.Start*1000), end_ms: (.End*1000), count: .Count}]' "$out")" "$st" \
    "fortio percentiles are fortio's histogram interpolation, not nearest-rank; runs = histogram buckets in ms" "${out#"$SPIKE_ROOT/"}"
  jq . <<<"$st"
}

# ---------------------------------------------------------------------------
# S6: fortio 50 connections for 60 s against podinfo-scale (target 10); pods
# and PodAutoscaler desired/actual every 2 s until 0 pods after the load.
s6() {
  local ksvc=podinfo-scale rev cfg stamp samp out fpid t0 st
  rev="$(latest_rev "$ksvc")"; cfg="$(config_json "$ksvc")"; stamp="$(ok211::stamp)"
  samp="$RAW/s6-pods-$stamp.tsv"; out="$RAW/s6-fortio-$stamp.json"
  wait_zero "$rev" 600
  printf 'utc\tt_s\tpods_running\tpods_total\tpa_desired\tpa_actual\n' > "$samp"
  t0="$(date -u +%s)"
  ( fortio_run S6 "$ksvc" 0 50 60s > "$out" ) &
  fpid=$!
  local load_done=0 dz=0
  while :; do
    local t pj pa
    t="$(date -u +%s)"
    pj="$("$K" -n "$NS" get pods -l "serving.knative.dev/revision=$rev" -o json | jq -r '[([.items[] | select(.status.phase=="Running" and .metadata.deletionTimestamp==null)] | length), (.items | length)] | @tsv')"
    pa="$("$K" -n "$NS" get podautoscaler "$rev" -o json | jq -r '[.status.desiredScale // "-", .status.actualScale // "-"] | @tsv')"
    printf '%s\t%s\t%s\t%s\n' "$(date -u +%FT%TZ)" "$((t - t0))" "$pj" "$pa" >> "$samp"
    if [ "$load_done" = 0 ] && ! kill -0 "$fpid" 2>/dev/null; then load_done=1; wait "$fpid"; fi
    if [ "$load_done" = 1 ] && [ "$(cut -f2 <<<"$pj")" = "0" ]; then dz=1; break; fi
    [ $((t - t0)) -lt 900 ] || break
    sleep 2
  done
  local logs="$RAW/s6-autoscaler-$stamp.log"
  "$K" -n knative-serving logs deploy/autoscaler --since=20m --timestamps \
    | grep -E "\"$NS/$rev\"|$rev" | grep -iE 'panic|PANICKING|Exiting panic|Operating in|desiredPodCount|scale' > "$logs" || true
  st="$(jq -c -n --rawfile s "$samp" --slurpfile f "$out" --argjson dz "$dz" '
    ($s | split("\n") | .[1:] | map(select(length>0) | split("\t") | {t: (.[1]|tonumber), running: (.[2]|tonumber), total: (.[3]|tonumber), desired: .[4], actual: .[5]})) as $x
    | ($x | map(.running) | max) as $mx
    | {max_running_pods: $mx, max_desired: ($x | map(.desired | tonumber? // 0) | max),
       first_t_at_max_s: ([$x[] | select(.running == $mx) | .t][0]),
       first_t_desired_ge_5_s: ([$x[] | select((.desired | tonumber? // 0) >= 5) | .t][0]),
       last_t_with_pods_s: ([$x[] | select(.total > 0) | .t] | max), reached_zero: ($dz == 1),
       fortio: ($f[0] | {actual_qps: .ActualQPS, count: .DurationHistogram.Count, codes: .RetCodes,
         p50_ms: ([.DurationHistogram.Percentiles[] | select(.Percentile==50) | .Value*1000][0]),
         p99_ms: ([.DurationHistogram.Percentiles[] | select(.Percentile==99) | .Value*1000][0]), max_ms: (.DurationHistogram.Max*1000)})}')"
  st="$(jq -c --arg panic "$(grep -ciE 'panic' "$logs" || true)" '. + {autoscaler_log_lines_with_panic: ($panic | tonumber)}' <<<"$st")"
  record S6 "$(jq -c '. + {fortio: {qps: "0 (max)", connections: 50, duration: "60s", warmup_s: 0}}' <<<"$cfg")" \
    "$(jq -R -s -c 'split("\n") | .[1:] | map(select(length>0) | split("\t") | {utc: .[0], t_s: (.[1]|tonumber), running: (.[2]|tonumber), total: (.[3]|tonumber), pa_desired: .[4], pa_actual: .[5]})' "$samp")" \
    "$st" "start from 0 pods (B11 state); no separate warm-up so the scale-up from zero is part of the series; t = seconds since the fortio Job was created; samples every 2 s" \
    "${samp#"$SPIKE_ROOT/"}" "${out#"$SPIKE_ROOT/"}" "${logs#"$SPIKE_ROOT/"}"
  jq . <<<"$st"
}

# node_stats <resources raw file>: mean/max of the "kubectl top nodes" section
# (sample, time, node, cpu, cpu%, mem, mem%). A function of its own: bash 3.2
# brace-expands the printf format when the awk program sits in a nested $(...).
node_stats() {
  awk -F'\t' '/^## kubectl top nodes/{f=1; next} /^## /{f=0}
    f && NF>=6 {c=$4; sub(/m$/,"",c); m=$6; sub(/Mi$/,"",m); n++; sc+=c; sm+=m; if (c+0>mc) mc=c+0; if (m+0>mm) mm=m+0}
    END {printf "{\"cpu_m_mean\":%.0f,\"cpu_m_max\":%d,\"mem_mi_mean\":%.0f,\"mem_mi_max\":%d}\n", sc/n, mc, sm/n, mm}' "$1"
}

# ---------------------------------------------------------------------------
# S10: no load. Namespace sums (usage mean/max over <samples>, requests,
# limits) via snapshot-resources.sh; queue-proxy usage and spec per pod of
# ok211-serving; delta to the Phase 2 baseline (resources.jsonl).
s10() {
  local samples="${1:-3}" interval="${2:-60}" out qp line base st
  "$SCRIPT_DIR/snapshot-resources.sh" s10-knative-1.24 "$samples" "$interval"
  line="$(tail -1 "$RAW/resources.jsonl")"
  base="$(grep '"id":"resources-baseline"' "$RAW/resources.jsonl" | head -1)"
  # The Phase 2 baseline line predates the node field: derive it from its raw file
  # (section "kubectl top nodes": sample, time, node, cpu, cpu%, mem, mem%).
  if [ "$(jq '.node' <<<"$base")" = "null" ]; then
    local bn
    bn="$(node_stats "$SPIKE_ROOT/$(jq -r .raw <<<"$base")")"
    base="$(jq -c --argjson n "$bn" '. + {node: $n}' <<<"$base")"
  fi
  out="$RAW/s10-queue-proxy-$(ok211::stamp).txt"
  "$K" top pods -n "$NS" --containers --no-headers > "$out"
  qp="$("$K" -n "$NS" get pods -o json | jq -c --rawfile top "$out" '
    ($top | split("\n") | map(select(length>0) | split(" ") | map(select(length>0)))
      | map({pod: .[0], container: .[1], cpu_m: (.[2] | rtrimstr("m") | tonumber), mem_mi: (.[3] | rtrimstr("Mi") | tonumber)})) as $t
    | [.items[] | .metadata.name as $p | {pod: $p, ksvc: .metadata.labels["serving.knative.dev/service"],
        queue_proxy: {spec: (.spec.containers[] | select(.name=="queue-proxy") | .resources),
                      usage: ([$t[] | select(.pod==$p and .container=="queue-proxy")][0] | {cpu_m, mem_mi})},
        user_container: {spec: (.spec.containers[] | select(.name!="queue-proxy") | .resources),
                      usage: ([$t[] | select(.pod==$p and .container!="queue-proxy")][0] | {cpu_m, mem_mi})}}]')"
  st="$(jq -cn --argjson l "$line" --argjson b "$base" --argjson qp "$qp" '
    def ns($n): ($l.namespaces[] | select(.namespace==$n)) // null;
    {namespaces: ($l.namespaces | map({namespace, cpu_m_mean, cpu_m_max, mem_mi_mean, mem_mi_max, req_cpu_m, req_mem_mi, lim_cpu_m, lim_mem_mi})),
     knative_total: ([$l.namespaces[] | select(.namespace | test("^(knative-serving|kourier-system|knative-eventing)$"))]
        | {cpu_m_mean: (map(.cpu_m_mean)|add), mem_mi_mean: (map(.mem_mi_mean)|add), req_cpu_m: (map(.req_cpu_m)|add), req_mem_mi: (map(.req_mem_mi)|add)}),
     node: $l.node, baseline_node: $b.node, queue_proxy_pods: $qp}')"
  record S10 "$(jq -c '{knative_version: .knative_version, note: "no load; podinfo-min1 keeps one pod"}' <<<"$(config_json podinfo)")" \
    "$(jq -c '[.samples_raw // empty]' <<<"$line")" "$st" \
    "usage from metrics-server (kubectl top), $samples samples ${interval} s apart; requests/limits from pod specs; baseline = Phase 2 empty cluster" \
    "$(jq -r '.raw' <<<"$line")" "${out#"$SPIKE_ROOT/"}"
  jq . <<<"$st"
}

# ---------------------------------------------------------------------------
apply_own() { "$SCRIPT_DIR/render.sh" "$@" | "$K" apply --server-side --field-manager=ok211 -f - >/dev/null; }

# versions <host> <n>: n requests from the probe, count the podinfo versions in the body.
versions() {
  # shellcheck disable=SC2016  # expanded inside the probe pod
  "$K" -n ok211-load exec ok211-probe -- sh -c '
    i=0; while [ "$i" -lt "$2" ]; do
      curl -sS --max-time 30 -H "Host: $1" "$3" | grep -o "\"version\": \"[0-9.]*\"" | cut -d\" -f4 || echo error
      i=$((i+1)); done | sort | uniq -c' _ "$1" "$2" "$KOURIER/"
}

# S8: revisions, 80/20 split with tag route candidate, rollback by traffic only.
s8() {
  local out cfg st r_split r_tag r_rb r_tag2 revs_before revs_after
  out="$RAW/s8-split-$(ok211::stamp).txt"
  # Start from scratch: revision names are fixed, step 1 must create v6160 anew.
  "$K" -n "$NS" delete ksvc podinfo-split --ignore-not-found --wait=true >/dev/null
  apply_own apps/serving/split/1-v6160.yaml
  "$K" -n "$NS" wait --for=condition=Ready ksvc/podinfo-split --timeout=300s >/dev/null
  apply_own apps/serving/split/2-split-80-20.yaml
  "$K" -n "$NS" wait --for=condition=Ready ksvc/podinfo-split --timeout=300s >/dev/null
  cfg="$(config_json podinfo-split)"
  {
    echo "# S8 $(ok211::timestamp)"; echo "## traffic after step 2"
    "$K" -n "$NS" get ksvc podinfo-split -o json | jq -c '.status.traffic'
    echo "## warm-up: 20 requests (both revisions get a pod)"; versions "$(host podinfo-split)" 20
  } >> "$out"
  r_split="$(versions "$(host podinfo-split)" 200)"
  r_tag="$(versions "candidate-$(host podinfo-split)" 20)"
  revs_before="$("$K" -n "$NS" get revisions -l serving.knative.dev/service=podinfo-split -o name | sort | tr '\n' ' ')"
  { echo "## 200 requests to podinfo-split"; echo "$r_split"; echo "## 20 requests to the tag host candidate-…"; echo "$r_tag"; echo "## revisions: $revs_before"; } >> "$out"
  apply_own apps/serving/split/3-rollback.yaml
  "$K" -n "$NS" wait --for=condition=Ready ksvc/podinfo-split --timeout=300s >/dev/null
  r_rb="$(versions "$(host podinfo-split)" 200)"
  r_tag2="$(versions "candidate-$(host podinfo-split)" 20)"
  revs_after="$("$K" -n "$NS" get revisions -l serving.knative.dev/service=podinfo-split -o name | sort | tr '\n' ' ')"
  { echo "## after rollback: traffic"; "$K" -n "$NS" get ksvc podinfo-split -o json | jq -c '.status.traffic'
    echo "## 200 requests after rollback"; echo "$r_rb"; echo "## 20 requests to the tag host after rollback"; echo "$r_tag2"
    echo "## revisions: $revs_after"; } >> "$out"
  cnt() { awk -v v="$2" '$2 == v {print $1}' <<<"$1" | head -1; }
  st="$(jq -cn --arg a "$(cnt "$r_split" 6.16.0)" --arg b "$(cnt "$r_split" 6.17.0)" --arg t "$(cnt "$r_tag" 6.17.0)" \
     --arg ta "$(cnt "$r_tag" 6.16.0)" --arg ra "$(cnt "$r_rb" 6.16.0)" --arg rb "$(cnt "$r_rb" 6.17.0)" --arg t2 "$(cnt "$r_tag2" 6.17.0)" \
     --arg rbf "$revs_before" --arg raf "$revs_after" '
     def n: if . == "" then 0 else tonumber end;
     {split_200: {"6.16.0": ($a|n), "6.17.0": ($b|n), share_new_pct: (($b|n) * 100 / 200)},
      tag_candidate_20: {"6.17.0": ($t|n), "6.16.0": ($ta|n)},
      rollback_200: {"6.16.0": ($ra|n), "6.17.0": ($rb|n)}, tag_after_rollback_20: {"6.17.0": ($t2|n)},
      revisions_before_rollback: $rbf, revisions_after_rollback: $raf, new_revision_on_rollback: ($rbf != $raf)}')"
  record S8 "$cfg" "[]" "$st" "versions counted from the podinfo JSON body; requests sequential from ok211-probe" "${out#"$SPIKE_ROOT/"}"
  cat "$out"; jq . <<<"$st"
}

# S9: timeoutSeconds 20, request /delay/30 (and /delay/10 as contrast).
s9() {
  local out cfg r30 r10 defaults
  out="$RAW/s9-timeout-$(ok211::stamp).txt"
  apply_own apps/serving/podinfo-timeout.yaml
  "$K" -n "$NS" wait --for=condition=Ready ksvc/podinfo-timeout --timeout=300s >/dev/null
  cfg="$(config_json podinfo-timeout)"
  defaults="$("$K" -n knative-serving get cm config-defaults -o json | jq -r '.data._example' | grep -E '^ *(revision-timeout-seconds|max-revision-timeout-seconds|revision-response-start-timeout-seconds|revision-idle-timeout-seconds):' | sed 's/^ *//')"
  probe_curl podinfo-timeout >/dev/null   # warm: the series measures the timeout, not a cold start
  r10="$(probe_curl podinfo-timeout /delay/10)"
  r30="$(probe_curl podinfo-timeout /delay/30)"
  { echo "# S9 $(ok211::timestamp)"; echo "## config-defaults (release defaults, no overrides)"; echo "$defaults"
    echo "## ksvc timeoutSeconds: $("$K" -n "$NS" get ksvc podinfo-timeout -o jsonpath='{.spec.template.spec.timeoutSeconds}')"
    echo "## vm_epoch code connect starttransfer total exit"; echo "/delay/10 $r10"; echo "/delay/30 $r30"; } > "$out"
  record S9 "$cfg" "$(jq -cn --arg a "$r10" --arg b "$r30" '[{path: "/delay/10", result: $a}, {path: "/delay/30", result: $b}]')" \
    "$(jq -cn --arg a "$r10" --arg b "$r30" '[$a, $b] | map(split(" ")) | {delay10: {code: .[0][1], total_s: (.[0][4]|tonumber)}, delay30: {code: .[1][1], total_s: (.[1][4]|tonumber), curl_exit: (.[1][5]|tonumber)}}')" \
    "result = vm_epoch code connect starttransfer total curl_exit; curl --max-time 120" "${out#"$SPIKE_ROOT/"}"
  cat "$out"
}

case "${1:-}" in
  s1) s1 ;;
  s2) s2 "${2:-3}" ;;
  coldstart) [ "$#" -eq 4 ] || ok211::die "usage: $0 coldstart <id> <ksvc> <n>" 2; coldstart "$2" "$3" "$4" ;;
  coldstart-eval) [ "$#" -eq 5 ] || ok211::die "usage: $0 coldstart-eval <id> <tsv> <revision> <image digest>" 2
    coldstart_eval "$2" "$3" "$(jq -c --arg img "$5" --arg rev "$4" '. + {revision: $rev, image_digest: $img}' <<<"$(config_json podinfo)")" ;;
  fortio) [ "$#" -ge 6 ] || ok211::die "usage: $0 fortio <id> <ksvc> <qps> <conns> <n|duration>" 2; fortio_cmd "$2" "$3" "$4" "$5" "$6" ;;
  s6) s6 ;;
  s8) s8 ;;
  s9) s9 ;;
  s10) s10 "${2:-3}" "${3:-60}" ;;
  config) config_json "$2" | jq . ;;
  *) ok211::die "usage: $0 s1|s2|coldstart|fortio|s6|s8|s9|s10|config" 2 ;;
esac
