#!/usr/bin/env bash
#
# OK-211 — collect and evaluate U1 (HTTP probe) and U2 (event flow) around the
# Knative upgrade (BRIEF B9 Phase 4, B11).
#
# Inputs
#   evidence/raw/upgrade-steps.log  UTC marks written by `make knative-upgrade`
#   pod logs (kubectl logs --timestamps): ok211-load/u1-probe,
#     ok211-events/u2-sender, ok211-events/deploy/event-display
# Window
#   upgrade window = first "start apply <to>/serving-crds.yaml" .. "end all
#   deployments on <to> Available"; after-run = 5 min after the window.
# Outputs
#   evidence/raw/u1-probe-<stamp>.log, u2-sender-<stamp>.log,
#   u2-received-<stamp>.tsv (one line per received event: kubelet time, type, id, seq)
#   evidence/raw/measurements.json (JSON Lines, ids U1 and U2, appended)
#   a summary on stdout
#
# Timestamps: kubelet prints RFC 3339 with the node's offset; everything is
# converted to UTC epoch milliseconds in jq.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
ok211::load_versions
K="${KUBECTL:-$SPIKE_ROOT/.local/bin/kubectl}"
# OK211_RAW_DIR / UPGRADE_STEPS redirect a dry run away from the real evidence.
RAW="${OK211_RAW_DIR:-$SPIKE_ROOT/evidence/raw}"
STEPS="${UPGRADE_STEPS:-$RAW/upgrade-steps.log}"
ok211::require_file "$STEPS" "upgrade-steps.log"
stamp="$(ok211::stamp)"
TO="${TO:-1.24}"

u1="$RAW/u1-probe-$stamp.log"
u2s="$RAW/u2-sender-$stamp.log"
u2r="$RAW/u2-received-$stamp.tsv"
"$K" -n ok211-load logs u1-probe --timestamps > "$u1"
"$K" -n ok211-events logs u2-sender --timestamps > "$u2s"
# event-display prints multi-line events; keep only type, id and seq, and the
# kubelet time of the line that carries the id.
"$K" -n ok211-events logs deploy/event-display --timestamps --tail=-1 \
  | awk '{ ts=$1; $1=""; sub(/^ +/,"") }
         /^type: /{t=$2} /^id: /{id=$2; idts=ts} /^seq: /{s=$2}
         /^Data,/{ if (id != "") print idts "\t" t "\t" id "\t" (s==""?"-":s); t=""; id=""; s="" }' > "$u2r"

# jq helpers shared by both evaluations.
# shellcheck disable=SC2016  # jq program, not shell expansions
JQ_LIB='
def ms: . as $s
  | ($s[0:19] | strptime("%Y-%m-%dT%H:%M:%S") | mktime) as $base
  | ([$s | capture("\\.(?<f>[0-9]+)")][0].f // "0") as $f
  | (($f + "000")[0:3] | tonumber) as $frac
  | ([$s | capture("(?<sign>[+-])(?<h>[0-9]{2}):(?<m>[0-9]{2})$")][0] // {sign:"+",h:"00",m:"00"}) as $o
  | (((($o.h|tonumber)*60 + ($o.m|tonumber))) * (if $o.sign == "+" then 1 else -1 end)) as $off
  | $base*1000 + $frac - $off*60000;
def pct($p): sort | if length == 0 then null else .[((length*$p/100)|ceil) - 1 | if . < 0 then 0 else . end] end;
def iso: (./1000 | floor | todate) as $d | ($d[0:19]) + "." + ((. % 1000) | tostring | ("00" + .)[-3:]) + "Z";
'

steps_json="$(jq -Rn "$JQ_LIB"'
  [inputs | split("\t") | select(length >= 3) | {ms: (.[0]|ms), ts: .[0], kind: .[1], what: .[2]}]' < "$STEPS")"
win_start="$(printf '%s' "$steps_json" | jq --arg to "$TO" '[.[] | select(.kind=="start" and .what == ("apply " + $to + "/serving-crds.yaml"))][0].ms')"
win_end="$(printf '%s' "$steps_json" | jq --arg to "$TO" '[.[] | select(.kind=="end" and .what == ("all deployments on " + $to + " Available"))][0].ms')"
[ "$win_start" != "null" ] && [ "$win_end" != "null" ] || ok211::die "upgrade window marks not found in upgrade-steps.log" 1
after_end=$(( win_end + 300000 ))

# Active step for a time: the most recent "start" mark at or before it.
# shellcheck disable=SC2016  # jq program
JQ_STEP='def step($t; $steps): ([$steps[] | select(.kind=="start" and .ms <= $t)] | last | .what) // "before";'

# ---------------------------------------------------------------------------
# U1
# ---------------------------------------------------------------------------
u1_json="$(jq -Rn --argjson ws "$win_start" --argjson we "$win_end" --argjson ae "$after_end" \
  --argjson steps "$steps_json" "$JQ_LIB$JQ_STEP"'
  [inputs | split(" ") | select(length >= 5)
    | {t: (.[0]|ms), seq: (.[1]|tonumber), code: .[2], lat_ms: ((.[3]|tonumber)*1000), rc: (.[4]|tonumber)}
    | .err = (.code != "200" or .rc != 0)] as $all
  | ($all | map(select(.t >= $ws and .t <= $we))) as $w
  | ($all | map(select(.t > $we and .t <= $ae))) as $a
  | ($w | map(select(.err))) as $we_err
  | {
      window: {start: ($ws|iso), end: ($we|iso), duration_s: (($we-$ws)/1000)},
      in_window: {requests: ($w|length), errors: ($we_err|length),
        error_rate_pct: (if ($w|length) == 0 then null else (($we_err|length)*10000/($w|length)|round/100) end),
        latency_ms: {p50: ($w|map(.lat_ms)|pct(50)), p90: ($w|map(.lat_ms)|pct(90)), p99: ($w|map(.lat_ms)|pct(99)), max: ($w|map(.lat_ms)|max)},
        errors_by_step: ($we_err | group_by(step(.t; $steps)) | map({step: step(.[0].t; $steps), count: length,
           codes: (map(.code + "/" + (.rc|tostring)) | group_by(.) | map({(.[0]): length}) | add),
           first: (.[0].t|iso), last: (.[-1].t|iso)})),
        slowest: ($w | sort_by(-.lat_ms) | .[0:5] | map({at: (.t|iso), lat_ms, code, rc, step: step(.t; $steps)}))},
      after_run: {requests: ($a|length), errors: ($a|map(select(.err))|length), duration_s: (($ae-$we)/1000),
        complete: (($all|map(.t)|max) >= $ae)},
      before_window: {requests: ($all|map(select(.t < $ws))|length), errors: ($all|map(select(.t < $ws and .err))|length)}
    }' < "$u1")"

# ---------------------------------------------------------------------------
# U2
# ---------------------------------------------------------------------------
u2_json="$(jq -n --rawfile sent "$u2s" --rawfile recv "$u2r" \
  --argjson ws "$win_start" --argjson we "$win_end" --argjson ae "$after_end" \
  --argjson steps "$steps_json" "$JQ_LIB$JQ_STEP"'
  ($sent | split("\n") | map(select(test("sent seq="))) | map(split(" ")
     | {t: (.[0]|ms), seq: (.[2]|ltrimstr("seq=")|tonumber), code: (.[3]|ltrimstr("code=")), rc: (.[4]|ltrimstr("exit=")|tonumber)})) as $s
  | ($recv | split("\n") | map(select(length > 0) | split("\t") | {t: (.[0]|ms), type: .[1], id: .[2], seq: .[3]})) as $r
  | ($r | map(select(.type == "dev.openkubes.ok211.upgrade"))) as $ru
  | ($ru | map(.seq|tonumber)) as $rseq
  | ($ru | group_by(.seq) | map(select(length > 1) | {seq: (.[0].seq|tonumber), copies: length})) as $dups
  | ($s | map(select(.t >= $ws and .t <= $ae))) as $sw
  | ($sw | map(select(.code == "202"))) as $acc
  | ($acc | map(.seq) - $rseq) as $lost
  | ($sw | map(select(.code != "202"))) as $rej
  | {
      window_incl_after_run: {start: ($ws|iso), end: ($ae|iso)},
      sent: ($sw|length), accepted_202: ($acc|length), rejected: ($rej|length),
      rejected_by_step: ($rej | group_by(step(.t; $steps)) | map({step: step(.[0].t; $steps), count: length,
          codes: (map(.code + "/" + (.rc|tostring)) | group_by(.) | map({(.[0]): length}) | add)})),
      delivered_unique: ($acc | map(.seq) | map(select(. as $q | $rseq | index($q))) | length),
      lost_after_202: ($lost|length), lost_seqs: $lost[0:50],
      lost_by_step: ($acc | map(select(.seq as $q | $lost | index($q))) | group_by(step(.t; $steps)) | map({step: step(.[0].t; $steps), count: length})),
      duplicates: ($dups|length), duplicate_detail: $dups[0:20],
      out_of_order: ([$ru | sort_by(.t) | .[].seq | tonumber] as $o | [range(1; $o|length) | select($o[.] < $o[.-1])] | length),
      recv_minus_sender_log_ms: ([$acc[] | .seq as $q | .t as $st | ($ru | map(select((.seq|tonumber) == $q)) | first) as $m
          | select($m != null) | $m.t - $st] | {p50: pct(50), p90: pct(90), max: max}),
      ping: {received_total: ($r | map(select(.type == "dev.knative.sources.ping")) | length),
        in_window: ($r | map(select(.type == "dev.knative.sources.ping" and .t >= $ws and .t <= $we)) | map(.t|iso)),
        window_minutes: (($we-$ws)/60000)}
    }')"

ts="$(ok211::timestamp)"
cfg="$(jq -cn --arg to "$TO" '{to: $to, probe_interval_ms: 200, curl_max_time_s: 5, ksvc: "podinfo-upgrade", min_scale: 1,
  sender_rate_per_s: 1, broker: "MTChannelBasedBroker/InMemoryChannel", broker_delivery: "retry 10, exponential, PT0.2S (config-br-defaults)"}')"
jq -cn --arg ts "$ts" --argjson cfg "$cfg" --argjson u1 "$u1_json" --arg raw "${u1#"$SPIKE_ROOT/"}" \
  '{id: "U1", timestamp_utc: $ts, knative_version: ("1.23 -> " + $cfg.to), config: $cfg, runs: [$raw], stats: $u1,
    notes: "error = HTTP != 200 or curl exit != 0; window = first CRD apply .. all deployments Available"}' >> "$RAW/measurements.json"
jq -cn --arg ts "$ts" --argjson cfg "$cfg" --argjson u2 "$u2_json" --arg raw1 "${u2s#"$SPIKE_ROOT/"}" --arg raw2 "${u2r#"$SPIKE_ROOT/"}" \
  '{id: "U2", timestamp_utc: $ts, knative_version: ("1.23 -> " + $cfg.to), config: $cfg, runs: [$raw1, $raw2], stats: $u2,
    notes: "lost = sender got 202 but event-display never logged the id; recv_minus_sender_log_ms uses the sender log line written after the 202, so it is not a delivery latency (E1 measures that)"}' >> "$RAW/measurements.json"

echo "== U1"; printf '%s\n' "$u1_json" | jq .
echo "== U2"; printf '%s\n' "$u2_json" | jq .
printf '\nraw: %s %s %s\n' "${u1#"$SPIKE_ROOT/"}" "${u2s#"$SPIKE_ROOT/"}" "${u2r#"$SPIKE_ROOT/"}"
