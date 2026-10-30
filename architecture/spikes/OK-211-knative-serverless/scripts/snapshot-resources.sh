#!/usr/bin/env bash
#
# OK-211 — resource snapshot per namespace (B11 "Ressourcen", baseline and S10).
#
# Usage: scripts/snapshot-resources.sh <label> [samples=3] [interval_s=60]
#
# Takes <samples> readings of `kubectl top nodes` and `kubectl top pods -A`
# (metrics-server) <interval_s> apart, plus `free -m` and `uptime` in the VM,
# and once the sum of requests/limits per namespace from the pod specs.
# Writes:
#   evidence/raw/resources-<label>-<stamp>.txt   raw readings
#   evidence/raw/resources.jsonl                 one JSON object per run (appended)
# and prints a per-namespace table (mean and max usage, requests, limits).
#
# The caller (make) runs the guard with --node first.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
ok211::load_versions

label="${1:-}"; samples="${2:-3}"; interval="${3:-60}"
[ -n "$label" ] || ok211::die "usage: $0 <label> [samples] [interval_s]" 2
K="${KUBECTL:-$SPIKE_ROOT/.local/bin/kubectl}"

stamp="$(ok211::stamp)"
raw="$SPIKE_ROOT/evidence/raw/resources-$label-$stamp.txt"
work="$SPIKE_ROOT/.local/tmp/resources-$stamp"; mkdir -p "$work"
: > "$work/pods.tsv"; : > "$work/nodes.tsv"

{
  printf '# resources %s — %s\n' "$label" "$(ok211::timestamp)"
  printf 'mac_loadavg: %s\n' "$(sysctl -n vm.loadavg)"
  printf 'vm_uptime: %s\n' "$(ok211::vm_ssh uptime)"
  printf 'vm_free_m:\n'; ok211::vm_ssh 'free -m' | sed 's/^/  /'
} > "$raw"

i=1
while [ "$i" -le "$samples" ]; do
  t="$(ok211::timestamp)"
  "$K" top nodes --no-headers | awk -v s="$i" -v t="$t" '{print s"\t"t"\t"$1"\t"$2"\t"$3"\t"$4"\t"$5}' >> "$work/nodes.tsv"
  "$K" top pods -A --no-headers | awk -v s="$i" -v t="$t" '{print s"\t"t"\t"$1"\t"$2"\t"$3"\t"$4}' >> "$work/pods.tsv"
  ok211::info "sample $i/$samples at $t"
  [ "$i" -lt "$samples" ] && sleep "$interval"
  i=$((i + 1))
done
{
  printf '\n## kubectl top nodes (sample, time, node, cpu, cpu%%, mem, mem%%)\n'; cat "$work/nodes.tsv"
  printf '\n## kubectl top pods -A (sample, time, namespace, pod, cpu, mem)\n'; cat "$work/pods.tsv"
} >> "$raw"

# Requests and limits from the specs (they decide schedulability, B11).
"$K" get pods -A -o json > "$work/pods.json"
jq -r '
  def cpu: if . == null then 0 elif test("m$") then (.[:-1]|tonumber) else (tonumber*1000) end;
  def mem: if . == null then 0
    elif test("Ki$") then (.[:-2]|tonumber/1024) elif test("Mi$") then (.[:-2]|tonumber)
    elif test("Gi$") then (.[:-2]|tonumber*1024) elif test("k$") then (.[:-1]|tonumber*1000/1048576)
    elif test("M$") then (.[:-1]|tonumber*1000000/1048576) elif test("G$") then (.[:-1]|tonumber*1000000000/1048576)
    else (tonumber/1048576) end;
  [.items[] | select(.status.phase == "Running") | .metadata.namespace as $ns | .spec.containers[] |
    {ns: $ns, rc: (.resources.requests.cpu|cpu), rm: (.resources.requests.memory|mem),
     lc: (.resources.limits.cpu|cpu), lm: (.resources.limits.memory|mem)}]
  | group_by(.ns)[] | [.[0].ns, (map(.rc)|add), (map(.rm)|add|floor), (map(.lc)|add), (map(.lm)|add|floor)] | @tsv
' "$work/pods.json" > "$work/specs.tsv"

# Usage per namespace: sum over pods per sample, then mean and max over samples.
awk -F'\t' '
  function c(v){ return (v ~ /m$/) ? substr(v,1,length(v)-1)+0 : v*1000 }
  function m(v){ if (v ~ /Mi$/) return substr(v,1,length(v)-2)+0; if (v ~ /Ki$/) return substr(v,1,length(v)-2)/1024; if (v ~ /Gi$/) return substr(v,1,length(v)-2)*1024; return v/1048576 }
  { k=$1 SUBSEP $3; cpu[k]+=c($5); mem[k]+=m($6); ns[$3]=1; smp[$1]=1 }
  END {
    n=0; for (s in smp) n++
    for (x in ns) {
      sc=0; sm=0; mc=0; mm=0
      for (s in smp) { k=s SUBSEP x; sc+=cpu[k]; sm+=mem[k]; if (cpu[k]>mc) mc=cpu[k]; if (mem[k]>mm) mm=mem[k] }
      printf "%s\t%.0f\t%.0f\t%.0f\t%.0f\n", x, sc/n, mc, sm/n, mm
    }
  }' "$work/pods.tsv" | sort > "$work/usage.tsv"

join -t "$(printf '\t')" -a 1 -e 0 -o 0,1.2,1.3,1.4,1.5,2.2,2.3,2.4,2.5 \
  "$work/usage.tsv" <(sort "$work/specs.tsv") > "$work/table.tsv"

# JSON line (B11 output format).
jq -cRn --arg id "resources-$label" --arg ts "$(ok211::timestamp)" --arg raw "${raw#"$SPIKE_ROOT/"}" \
  --argjson samples "$samples" --argjson interval "$interval" '
  [inputs | split("\t") | {namespace: .[0], cpu_m_mean: (.[1]|tonumber), cpu_m_max: (.[2]|tonumber),
    mem_mi_mean: (.[3]|tonumber), mem_mi_max: (.[4]|tonumber), req_cpu_m: (.[5]|tonumber),
    req_mem_mi: (.[6]|tonumber), lim_cpu_m: (.[7]|tonumber), lim_mem_mi: (.[8]|tonumber)}]
  | {id: $id, timestamp_utc: $ts, samples: $samples, interval_s: $interval, raw: $raw, namespaces: .}
' < "$work/table.tsv" >> "$SPIKE_ROOT/evidence/raw/resources.jsonl"

printf 'namespace\tcpu_m_mean\tcpu_m_max\tmem_Mi_mean\tmem_Mi_max\treq_cpu_m\treq_mem_Mi\tlim_cpu_m\tlim_mem_Mi\n' > "$work/out.tsv"
cat "$work/table.tsv" >> "$work/out.tsv"
awk -F"\t" '{a+=$2; b+=$4; c+=$6; d+=$7} END{printf "TOTAL\t%d\t-\t%d\t-\t%d\t%d\t-\t-\n", a, b, c, d}' "$work/table.tsv" >> "$work/out.tsv"
{ printf '\n## per-namespace summary\n'; cat "$work/out.tsv"; } >> "$raw"
column -t -s "$(printf '\t')" < "$work/out.tsv"
printf '\nraw: %s\n' "${raw#"$SPIKE_ROOT/"}"
rm -rf "$work"
