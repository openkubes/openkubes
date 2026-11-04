#!/usr/bin/env bash
#
# OK-211 — Eventing measurements E1-E8 (BRIEF B9 Phase 6, B11).
#
# Usage: scripts/measure-eventing.sh <cmd>
#   e1          20 events (binary and structured mode, alternating) to the broker, trigger on type
#   e2 [runs]   event to event-display-ksvc at 0 pods, delivery including cold start (5 runs)
#   e3          two triggers (type filter, source filter), 15 events, who got what
#   e4          retries (retry 3, exponential PT0.5S) against /status/500, dead-letter sink
#   e5 <dispatcher|ingress|restart|none>   100 events at 5/s while the sink is down; the
#               imc-dispatcher or mt-broker-ingress pod is force-deleted (or the
#               dispatcher is rollout-restarted) during the run; "none" is the control run
#   e6          PingSource cycles seen by event-display since the base was applied
#   e8          the recorded zot event from OK-167 (apps/eventing/e8-zot-event.json)
#
# Senders run as Jobs in ok211-load (curl image, PSA restricted). Each sender
# logs "send <id>" before and "sent <id> code=<http> exit=<curl>" after every
# POST. Latency = kubelet timestamp of the sink's "id:" line minus that of
# the sender's "send <id>" line (one node, one clock; B11).
# The caller (make) runs the guard with --node first.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
ok211::load_versions

K="${KUBECTL:-$SPIKE_ROOT/.local/bin/kubectl}"
RAW="$SPIKE_ROOT/evidence/raw"
NS=ok211-events
BROKER=http://broker-ingress.knative-eventing.svc.cluster.local/ok211-events/default

# shellcheck disable=SC2016  # jq programs
JQ_LIB='
def ms: . as $s
  | ($s[0:19] | strptime("%Y-%m-%dT%H:%M:%S") | mktime) as $base
  | ([$s | capture("\\.(?<f>[0-9]+)")][0].f // "0") as $f
  | (($f + "000")[0:3] | tonumber) as $frac
  | ([$s | capture("(?<sign>[+-])(?<h>[0-9]{2}):(?<m>[0-9]{2})$")][0] // {sign:"+",h:"00",m:"00"}) as $o
  | (((($o.h|tonumber)*60 + ($o.m|tonumber))) * (if $o.sign == "+" then 1 else -1 end)) as $off
  | $base*1000 + $frac - $off*60000;
def nr($p): sort | if length == 0 then null else .[((length*$p/100)|ceil) - 1 | if . < 0 then 0 else . end] end;
def stats: if length == 0 then {n: 0}
  elif length < 10 then {n: length, min: min, median: nr(50), max: max}
  else {n: length, min: min, median: nr(50), p90: nr(90), max: max} end;
'

apply_own() { "$SCRIPT_DIR/render.sh" "$@" | "$K" apply --server-side --field-manager=ok211 -f - >/dev/null; }

config_json() {
  jq -cn --arg v "$("$K" -n knative-eventing get deploy eventing-controller -o jsonpath='{.metadata.labels.app\.kubernetes\.io/version}')" \
    --argjson br "$("$K" -n knative-eventing get cm config-br-defaults -o json | jq -c '.data')" \
    --argjson trig "$("$K" -n "$NS" get triggers -o json | jq -c '[.items[] | {name: .metadata.name, filter: .spec.filter, subscriber: .spec.subscriber, delivery: .spec.delivery}]')" \
    '{knative_version: $v, broker: "default (MTChannelBasedBroker)", config_br_defaults: $br, triggers: $trig}'
}

record() { # record <id> <config json> <runs json> <stats json> <notes> [raw files...]
  local id="$1" cfg="$2" runs="$3" st="$4" notes="$5"; shift 5
  local raw; raw="$(printf '%s\n' "$@" | jq -R . | jq -s -c 'map(select(length > 0))')"
  jq -cn --arg id "$id" --arg ts "$(ok211::timestamp)" --argjson cfg "$cfg" --argjson runs "$runs" \
    --argjson st "$st" --arg notes "$notes" --argjson raw "$raw" \
    '{id: $id, timestamp_utc: $ts, knative_version: $cfg.knative_version, config: $cfg, runs: $runs, stats: $st, notes: $notes, raw: $raw}' \
    >> "$RAW/measurements.json"
}

# sender_start <name> <n> <interval_s> <type> <source> <id prefix> <mode binary|structured|alternate> [async 0|1] [max_time_s]
# Creates the sender Job and returns at once. The memory limit allows up to
# 100 concurrent curl processes (64Mi was OOMKilled at ~43). With async=1 every POST runs in
# the background, so the rate stays fixed even when the broker answers late:
# with MT broker + InMemoryChannel the 202 only comes after delivery (E2, E4).
sender_start() {
  local name="$1"
  # shellcheck disable=SC2016  # runs inside the sender pod
  local script='
i=0
while [ "$i" -lt "$N" ]; do
  i=$((i+1)); id="$PREFIX-$i"
  m="$MODE"; if [ "$m" = alternate ]; then if [ $((i % 2)) -eq 1 ]; then m=binary; else m=structured; fi; fi
  echo "send $id seq=$i mode=$m"
  (
  if [ "$m" = binary ]; then
    code=$(curl -sS -o /dev/null --max-time "$MAXTIME" -w "%{http_code}" -X POST "$BROKER" \
      -H "Ce-Id: $id" -H "Ce-Specversion: 1.0" -H "Ce-Type: $TYPE" -H "Ce-Source: $SOURCE" -H "Ce-Seq: $i" \
      -H "Content-Type: application/json" -d "{\"seq\": $i}" 2>/dev/null); rc=$?
  else
    code=$(curl -sS -o /dev/null --max-time "$MAXTIME" -w "%{http_code}" -X POST "$BROKER" \
      -H "Content-Type: application/cloudevents+json" \
      -d "{\"specversion\":\"1.0\",\"id\":\"$id\",\"type\":\"$TYPE\",\"source\":\"$SOURCE\",\"seq\":\"$i\",\"datacontenttype\":\"application/json\",\"data\":{\"seq\":$i}}" 2>/dev/null); rc=$?
  fi
  echo "sent $id code=${code:-000} exit=$rc"
  ) &
  if [ "$ASYNC" != 1 ]; then wait; fi
  sleep "$INTERVAL"
done
wait'
  jq -n --arg name "$name" --arg img "$CURL_IMAGE" --arg script "$script" --arg n "$2" --arg iv "$3" \
    --arg type "$4" --arg src "$5" --arg prefix "$6" --arg mode "$7" --arg broker "$BROKER" \
    --arg async "${8:-0}" --arg maxt "${9:-30}" '{
    apiVersion: "batch/v1", kind: "Job",
    metadata: {name: $name, namespace: "ok211-load", labels: {"app.kubernetes.io/part-of": "ok211", "app.kubernetes.io/name": "event-sender"}},
    spec: {backoffLimit: 0, ttlSecondsAfterFinished: 3600, template: {
      metadata: {labels: {"app.kubernetes.io/name": "event-sender"}},
      spec: {restartPolicy: "Never", automountServiceAccountToken: false, terminationGracePeriodSeconds: 1,
        securityContext: {runAsNonRoot: true, runAsUser: 100, runAsGroup: 101, seccompProfile: {type: "RuntimeDefault"}},
        containers: [{name: "sender", image: $img, command: ["sh", "-c", $script],
          env: [{name: "N", value: $n}, {name: "INTERVAL", value: $iv}, {name: "TYPE", value: $type},
                {name: "SOURCE", value: $src}, {name: "PREFIX", value: $prefix}, {name: "MODE", value: $mode},
                {name: "BROKER", value: $broker}, {name: "ASYNC", value: $async}, {name: "MAXTIME", value: $maxt}],
          securityContext: {allowPrivilegeEscalation: false, readOnlyRootFilesystem: true, capabilities: {drop: ["ALL"]}},
          resources: {requests: {cpu: "10m", memory: "16Mi"}, limits: {cpu: "1", memory: "512Mi"}}}]}}}}' \
    | "$K" create -f - >/dev/null
}

sender_wait() { # sender_wait <name> <out file>
  "$K" -n ok211-load wait --for=condition=Complete --timeout=600s "job/$1" >/dev/null
  "$K" -n ok211-load logs "job/$1" --timestamps > "$2"
}

# sink_tsv <kubectl logs selector args...> -> TSV: kubelet time of the id line, type, source, id, extensions (k=v;...)
sink_tsv() {
  "$K" -n "$NS" logs "$@" --timestamps --tail=-1 2>/dev/null | awk '
    function flush() { if (id != "") print idts "\t" t "\t" src "\t" id "\t" ext; t=""; src=""; id=""; ext=""; idts="" }
    { ts=$1; $1=""; sub(/^ +/, "") }
    /cloudevents.Event/ { flush(); sec=""; next }
    /^Context Attributes,/ { sec="ctx"; next }
    /^Extensions,/ { sec="ext"; next }
    /^Data,/ { sec="data"; next }
    sec == "ctx" && /^type: / { t=$2 }
    sec == "ctx" && /^source: / { src=$2 }
    sec == "ctx" && /^id: / { id=$2; idts=ts }
    sec == "ext" && /^[a-z0-9]+: / { k=$1; sub(/:$/, "", k); v=$0; sub(/^[a-z0-9]+: /, "", v); ext=ext (ext == "" ? "" : ";") k "=" v }
    END { flush() }'
}

# latency_json <sender log> <sink tsv> <id prefix>: per accepted id, sink minus send in ms.
latency_json() {
  jq -n --rawfile s "$1" --rawfile r "$2" --arg p "$3" "$JQ_LIB"'
    ($s | split("\n") | map(select(test(" send "))) | map(split(" ") | {t: (.[0]|ms), id: .[2]})) as $send
    | ($s | split("\n") | map(select(test(" sent "))) | map(split(" ") | {id: .[2], code: (.[3]|ltrimstr("code=")), rc: (.[4]|ltrimstr("exit=")|tonumber)})) as $sent
    | ($r | split("\n") | map(select(length > 0) | split("\t") | {t: (.[0]|ms), type: .[1], source: .[2], id: .[3], ext: .[4]}) | map(select(.id | startswith($p + "-")))) as $recv
    | [$send[] | .id as $i | .t as $t0
        | ($sent | map(select(.id == $i)) | first) as $res
        | ($recv | map(select(.id == $i))) as $m
        | {id: $i, code: $res.code, curl_exit: $res.rc, copies: ($m | length),
           latency_ms: (if ($m | length) > 0 then ($m[0].t - $t0) else null end)}]'
}

wait_ready() { "$K" -n "$NS" wait --for=condition=Ready "$@" --timeout=300s >/dev/null; }

# ---------------------------------------------------------------------------
e1() {
  local stamp s r runs st
  stamp="$(ok211::stamp)"; s="$RAW/e1-sender-$stamp.log"; r="$RAW/e1-sink-$stamp.tsv"
  wait_ready broker/default trigger/e1-test
  sender_start "e1-$(date -u +%H%M%S)" 20 0.5 dev.openkubes.ok211.test /ok211/e1 "e1-$stamp" alternate
  sender_wait "$(newest_job e1-)" "$s"
  sleep 5
  sink_tsv deploy/event-display > "$r"
  runs="$(latency_json "$s" "$r" "e1-$stamp")"
  st="$(jq -c "$JQ_LIB"'{sent: length, accepted_202: (map(select(.code == "202")) | length), delivered: (map(select(.copies > 0)) | length),
      duplicates: (map(select(.copies > 1)) | length), latency_ms: (map(.latency_ms // empty) | stats),
      binary: (to_entries | map(select(.key % 2 == 0)) | map(.value) | {delivered: (map(select(.copies > 0)) | length), latency_ms: (map(.latency_ms // empty) | stats)}),
      structured: (to_entries | map(select(.key % 2 == 1)) | map(.value) | {delivered: (map(select(.copies > 0)) | length), latency_ms: (map(.latency_ms // empty) | stats)})}' <<<"$runs")"
  record E1 "$(config_json)" "$runs" "$st" "odd seq = binary mode, even seq = structured mode; 0.5 s between events; latency = sink id line - sender send line (kubelet timestamps)" "${s#"$SPIKE_ROOT/"}" "${r#"$SPIKE_ROOT/"}"
  jq . <<<"$st"
}

newest_job() { "$K" -n ok211-load get jobs -o json | jq -r --arg p "$1" '[.items[] | select(.metadata.name | startswith($p))] | sort_by(.metadata.creationTimestamp) | last | .metadata.name'; }

# ---------------------------------------------------------------------------
# E2: B11 zero state of event-display-ksvc before each run, one event, poll the
# sink pod's log until the id shows up (the pod's log disappears with the pod).
e2() {
  local n="${1:-5}" stamp rev i s r out runs="[]" id t0 st
  stamp="$(ok211::stamp)"; out="$RAW/e2-$stamp.tsv"
  wait_ready ksvc/event-display-ksvc trigger/e2-ksvc
  rev="$("$K" -n "$NS" get ksvc event-display-ksvc -o jsonpath='{.status.latestReadyRevisionName}')"
  printf 'run\tid\tcode\tlatency_ms\tpod\n' > "$out"
  for i in $(seq 1 "$n"); do
    t0="$(date -u +%s)"
    while :; do
      [ "$("$K" -n "$NS" get pods -l "serving.knative.dev/revision=$rev" -o json | jq '.items | length')" = 0 ] \
        && [ "$("$K" -n "$NS" get podautoscaler "$rev" -o jsonpath='{.status.actualScale}')" = 0 ] \
        && [ "$("$K" -n "$NS" get sks "$rev" -o jsonpath='{.spec.mode}')" = Proxy ] && break
      [ $(( $(date -u +%s) - t0 )) -lt 600 ] || ok211::die "E2: $rev not at zero after 600 s" 1
      sleep 2
    done
    sleep 10
    id="e2-$stamp-r$i"
    s="$RAW/e2-sender-$stamp-r$i.log"; r="$RAW/e2-sink-$stamp-r$i.tsv"
    sender_start "e2-r$i-$(date -u +%H%M%S)" 1 0 dev.openkubes.ok211.e2 /ok211/e2 "$id" binary
    sender_wait "$(newest_job "e2-r$i-")" "$s"
    t0="$(date -u +%s)"
    while :; do
      sink_tsv -l "serving.knative.dev/revision=$rev" -c event-display > "$r" || true
      grep -q "	$id-1	" "$r" && break
      [ $(( $(date -u +%s) - t0 )) -lt 180 ] || { ok211::warn "E2 run $i: $id not seen within 180 s"; break; }
      sleep 1
    done
    local lj; lj="$(latency_json "$s" "$r" "$id")"
    runs="$(jq -c --argjson i "$i" --argjson l "$lj" '. + [($l[0] + {run: $i})]' <<<"$runs")"
    printf '%s\t%s\t%s\t%s\t%s\n' "$i" "$id-1" "$(jq -r '.[0].code' <<<"$lj")" "$(jq -r '.[0].latency_ms' <<<"$lj")" \
      "$("$K" -n "$NS" get pods -l "serving.knative.dev/revision=$rev" -o name | head -1)" >> "$out"
    ok211::ok "E2 run $i/$n: $(jq -r '.[0] | "code \(.code), latency \(.latency_ms) ms"' <<<"$lj")"
  done
  st="$(jq -c "$JQ_LIB"'{runs: length, accepted_202: (map(select(.code == "202")) | length), delivered: (map(select(.copies > 0)) | length),
      latency_ms: (map(.latency_ms // empty) | stats)}' <<<"$runs")"
  record E2 "$(config_json | jq -c --arg rev "$rev" '. + {ksvc: "event-display-ksvc", revision: $rev, annotations: {"autoscaling.knative.dev/window": "6s"}}')" \
    "$runs" "$st" "each run from the B11 zero state + 10 s; latency = sink id line - sender send line, includes the cold start; the 202 is returned before delivery" "${out#"$SPIKE_ROOT/"}"
  jq . <<<"$st"
}

# ---------------------------------------------------------------------------
e3() {
  local stamp out ra rb
  stamp="$(ok211::stamp)"; out="$RAW/e3-$stamp.txt"
  wait_ready trigger/e3-a trigger/e3-b
  sender_start "e3-a-$(date -u +%H%M%S)" 5 0.2 dev.openkubes.ok211.e3.a /ok211/e3/x "e3a-$stamp" binary
  sender_start "e3-b-$(date -u +%H%M%S)" 5 0.2 dev.openkubes.ok211.e3.z /ok211/e3/b "e3b-$stamp" binary
  sender_start "e3-z-$(date -u +%H%M%S)" 5 0.2 dev.openkubes.ok211.e3.z /ok211/e3/z "e3z-$stamp" binary
  for p in e3-a- e3-b- e3-z-; do "$K" -n ok211-load wait --for=condition=Complete --timeout=300s "job/$(newest_job "$p")" >/dev/null; done
  sleep 5
  ra="$(sink_tsv deploy/sink-a | grep -F -- "-$stamp-" || true)"; rb="$(sink_tsv deploy/sink-b | grep -F -- "-$stamp-" || true)"
  { echo "# E3 $(ok211::timestamp)"
    echo "## sent: e3a-* type dev.openkubes.ok211.e3.a source /ok211/e3/x; e3b-* type …e3.z source /ok211/e3/b; e3z-* type …e3.z source /ok211/e3/z (5 each)"
    echo "## sink-a (trigger e3-a: type=dev.openkubes.ok211.e3.a)"; echo "$ra"
    echo "## sink-b (trigger e3-b: source=/ok211/e3/b)"; echo "$rb"; } > "$out"
  local st
  st="$(jq -cn --arg a "$ra" --arg b "$rb" '
    def ids($x): $x | split("\n") | map(select(length > 0) | split("\t")[3]);
    def by($l; $p): $l | map(select(startswith($p))) | length;
    {sink_a: {e3a: by(ids($a); "e3a-"), e3b: by(ids($a); "e3b-"), e3z: by(ids($a); "e3z-")},
     sink_b: {e3a: by(ids($b); "e3a-"), e3b: by(ids($b); "e3b-"), e3z: by(ids($b); "e3z-")}}')"
  record E3 "$(config_json)" "[]" "$st" "expected: sink-a only e3a (5), sink-b only e3b (5), e3z nowhere" "${out#"$SPIKE_ROOT/"}"
  cat "$out"; jq . <<<"$st"
}

# ---------------------------------------------------------------------------
e4() {
  local stamp s out dls pl id rev pod st
  stamp="$(ok211::stamp)"; s="$RAW/e4-sender-$stamp.log"; out="$RAW/e4-$stamp.txt"
  wait_ready ksvc/podinfo-fail trigger/e4-retry
  rev="$("$K" -n "$NS" get ksvc podinfo-fail -o jsonpath='{.status.latestReadyRevisionName}')"
  pod="$("$K" -n "$NS" get pods -l "serving.knative.dev/revision=$rev" -o name | head -1)"
  id="e4-$stamp"
  sender_start "e4-$(date -u +%H%M%S)" 1 0 dev.openkubes.ok211.e4 /ok211/e4 "$id" binary
  sender_wait "$(newest_job e4-)" "$s"
  sleep 20
  pl="$("$K" -n "$NS" logs "$pod" -c podinfo --timestamps | grep '/status/500' || true)"
  dls="$(sink_tsv deploy/event-display-dls | grep -F "	$id-1	" || true)"
  { echo "# E4 $(ok211::timestamp)"; echo "## sender"; cat "$s"
    echo "## podinfo-fail requests to /status/500 ($pod)"; echo "$pl"
    echo "## dead-letter sink event-display-dls"; echo "$dls"
    echo "## full DLS log entry"; "$K" -n "$NS" logs deploy/event-display-dls --tail=60 | awk -v id="$id-1" '/cloudevents.Event/{buf=""} {buf=buf $0 "\n"} $0 ~ "id: " id {f=1} f && /^Data,/{print buf; exit}'
  } > "$out"
  st="$(jq -cn --arg pl "$pl" --arg dls "$dls" --arg sent "$(grep ' sent ' "$s")" '
    {attempts_seen_by_subscriber: ($pl | split("\n") | map(select(length > 0)) | length),
     expected_attempts: 4, sender: $sent,
     dls_received: ($dls | length > 0),
     dls_extensions: ($dls | split("\t")[4] // "" | split(";") | map(select(length > 0) | split("=") | {(.[0]): (.[1:] | join("="))}) | add)}')"
  record E4 "$(config_json)" "$(jq -cn --arg pl "$pl" '$pl | split("\n") | map(select(length > 0))')" "$st" \
    "attempts counted from podinfo debug logs (one line per request to /status/500); retry 3 => 1 + 3 attempts" "${out#"$SPIKE_ROOT/"}" "${s#"$SPIKE_ROOT/"}"
  jq . <<<"$st"
}

# ---------------------------------------------------------------------------
# E5 <dispatcher|ingress|restart>: sink-e5 scaled to 0, 100 events at 5/s;
# at t ≈ 8 s the disruption; at t ≈ 14 s the sink comes back, so the first
# events still have retries left (window ≤ 31 s); then wait and count.
e5() {
  local scen="$1" stamp s r out job t_dis t_up st
  case "$scen" in dispatcher|ingress|restart|none) : ;; *) ok211::die "usage: e5 dispatcher|ingress|restart|none" 2 ;; esac
  stamp="$(ok211::stamp)"; s="$RAW/e5-$scen-sender-$stamp.log"; r="$RAW/e5-$scen-sink-$stamp.tsv"; out="$RAW/e5-$scen-$stamp.txt"
  wait_ready trigger/e5-durable
  "$K" -n "$NS" scale deploy/sink-e5 --replicas=0 >/dev/null
  "$K" -n "$NS" wait --for=delete pod -l app.kubernetes.io/name=sink-e5 --timeout=120s >/dev/null 2>&1 || true
  job="e5-$scen-$(date -u +%H%M%S)"
  sender_start "$job" 100 0.2 dev.openkubes.ok211.e5 /ok211/e5 "e5$scen-$stamp" binary 1 90
  # The Job's pod does not exist right after create; wait for it, then for Ready.
  for _ in $(seq 1 60); do
    [ -n "$("$K" -n ok211-load get pods -l "job-name=$job" -o name)" ] && break; sleep 1
  done
  "$K" -n ok211-load wait --for=condition=Ready pod -l "job-name=$job" --timeout=120s >/dev/null
  sleep 8
  t_dis="$(ok211::timestamp)"
  case "$scen" in
    dispatcher) "$K" -n knative-eventing delete pod -l messaging.knative.dev/channel=in-memory-channel,messaging.knative.dev/role=dispatcher --grace-period=0 --force >/dev/null 2>&1 ;;
    ingress) "$K" -n knative-eventing delete pod -l eventing.knative.dev/brokerRole=ingress --grace-period=0 --force >/dev/null 2>&1 ;;
    restart) "$K" -n knative-eventing rollout restart deploy/imc-dispatcher >/dev/null ;;
    none) : ;;  # control run: same sink outage, no disruption
  esac
  sleep 6
  t_up="$(ok211::timestamp)"
  "$K" -n "$NS" scale deploy/sink-e5 --replicas=1 >/dev/null
  sender_wait "$job" "$s"
  "$K" -n "$NS" rollout status deploy/sink-e5 --timeout=120s >/dev/null
  sleep 60
  sink_tsv deploy/sink-e5 > "$r"
  { echo "# E5 $scen $(ok211::timestamp)"; echo "disruption at $t_dis, sink scaled to 1 at $t_up"
    "$K" -n knative-eventing get pods -o wide | grep -E 'imc-dispatcher|mt-broker-ingress'; } > "$out"
  local lj; lj="$(latency_json "$s" "$r" "e5$scen-$stamp")"
  st="$(jq -c --arg td "$t_dis" --arg tu "$t_up" --rawfile r "$r" --arg p "e5$scen-$stamp" '
    ($r | split("\n") | map(select(length > 0) | split("\t")[3]) | map(select(startswith($p + "-"))) | map(ltrimstr($p + "-") | tonumber)) as $order
    | {scenario: "'"$scen"'", disruption_utc: $td, sink_back_utc: $tu, sent: length,
       accepted_202: (map(select(.code == "202")) | length),
       rejected: (map(select(.code != "202")) | map(.code + "/" + (.curl_exit|tostring)) | group_by(.) | map({(.[0]): length}) | add),
       delivered_unique: (map(select(.copies > 0)) | length),
       lost_after_202: (map(select(.code == "202" and .copies == 0)) | length),
       lost_ids: (map(select(.code == "202" and .copies == 0) | .id | split("-") | last | tonumber)),
       duplicates: (map(select(.copies > 1)) | length),
       out_of_order: ([range(1; $order | length) | select($order[.] < $order[. - 1])] | length),
       delivery_order_first_20: $order[0:20]}' <<<"$lj")"
  record "E5-$scen" "$(config_json)" "$lj" "$st" \
    "sink-e5 at 0 replicas from before the first event until sink_back_utc, so events wait in the dispatcher's retry loop (trigger retry 5, exponential PT1S); disruption at t≈8 s, sink back at t≈14 s after the sender pod was Ready; sender async at 5/s, curl --max-time 90; the broker answers only after delivery or final failure" \
    "${s#"$SPIKE_ROOT/"}" "${r#"$SPIKE_ROOT/"}" "${out#"$SPIKE_ROOT/"}"
  jq . <<<"$st"
}

# ---------------------------------------------------------------------------
e6() {
  local r st since
  r="$RAW/e6-ping-$(ok211::stamp).tsv"
  since="$("$K" -n "$NS" get pingsource ok211-ping -o jsonpath='{.metadata.creationTimestamp}')"
  sink_tsv deploy/event-display | awk -F'\t' '$2 == "dev.knative.sources.ping"' > "$r"
  st="$(jq -n --rawfile r "$r" --arg since "$since" "$JQ_LIB"'
    ($r | split("\n") | map(select(length > 0) | split("\t") | {t: .[0], ms: (.[0]|ms), id: .[3]})) as $p
    | ($p | map(.t[0:16])) as $mins
    | {pingsource_created: $since, received: ($p | length), distinct_minutes: ($mins | unique | length),
       duplicates_per_minute: ($mins | group_by(.) | map(select(length > 1)) | length),
       first: ($p[0].t // null), last: ($p[-1].t // null),
       offset_in_minute_ms: ($p | map(.ms % 60000) | stats)}')"
  record E6 "$(config_json)" "$(jq -R -s -c 'split("\n") | map(select(length > 0) | split("\t") | {t: .[0], id: .[3]})' "$r")" "$st" \
    "PingSource schedule * * * * *; one event per minute expected; offset = ms after the full minute at which event-display logged it" "${r#"$SPIKE_ROOT/"}"
  jq . <<<"$st"
}

# ---------------------------------------------------------------------------
e8() {
  local f="$SPIKE_ROOT/apps/eventing/e8-zot-event.json" id out code r
  out="$RAW/e8-zot-$(ok211::stamp).txt"
  wait_ready trigger/e8-zot
  id="$(jq -r '.ce_headers["ce-id"]' "$f")"
  # Binary mode exactly as zot sent it: its ce-* headers and its JSON body.
  # shellcheck disable=SC2016  # expanded inside the probe pod
  code="$("$K" -n ok211-load exec -i ok211-probe -- sh -c '
    curl -sS -o /dev/null -w "%{http_code}" -X POST "$1" -H "Content-Type: application/json" \
      -H "Ce-Id: $2" -H "Ce-Source: $3" -H "Ce-Specversion: $4" -H "Ce-Time: $5" -H "Ce-Type: $6" --data-binary @-' _ \
      "$BROKER" "$id" "$(jq -r '.ce_headers["ce-source"]' "$f")" "$(jq -r '.ce_headers["ce-specversion"]' "$f")" \
      "$(jq -r '.ce_headers["ce-time"]' "$f")" "$(jq -r '.ce_headers["ce-type"]' "$f")" < <(jq -c .body "$f"))"
  sleep 5
  r="$(sink_tsv deploy/event-display | grep -F "	$id	" || true)"
  { echo "# E8 $(ok211::timestamp)"; echo "source file: apps/eventing/e8-zot-event.json (copy of OK-167 evidence/raw/cloudevent-image-updated.json)"
    echo "broker response: $code"; echo "## event-display"; echo "$r"
    "$K" -n "$NS" logs deploy/event-display --tail=80 | awk -v id="$id" '/cloudevents.Event/{buf=""} {buf=buf $0 "\n"} $0 ~ "id: " id {f=1} f && /"reference"/{print buf; exit}'; } > "$out"
  record E8 "$(config_json)" "[]" "$(jq -cn --arg c "$code" --arg r "$r" '{broker_response: $c, routed_to_event_display: ($r | length > 0)}')" \
    "trigger e8-zot filters type=zotregistry.image.updated" "${out#"$SPIKE_ROOT/"}"
  cat "$out"
}

case "${1:-}" in
  e1) e1 ;;
  e2) e2 "${2:-5}" ;;
  e3) e3 ;;
  e4) e4 ;;
  e5) e5 "${2:-}" ;;
  e6) e6 ;;
  e8) e8 ;;
  *) ok211::die "usage: $0 e1|e2|e3|e4|e5 <scenario>|e6|e8" 2 ;;
esac
