#!/usr/bin/env bash
#
# OK-211 — security experiments X1-X5 (BRIEF B9 Phase 8).
#
# Usage: scripts/security.sh x1
#   x1  Pod Security restricted in ok211-tenant-a; run A with config-features
#       secure-pod-defaults as released (disabled), run B with Enabled, then
#       restore (disabled, services deleted, namespace kept)
# The caller (make) runs the guard with --node first.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
ok211::load_versions

K="${KUBECTL:-$SPIKE_ROOT/.local/bin/kubectl}"
RAW="$SPIKE_ROOT/evidence/raw"

apply_own() { "$SCRIPT_DIR/render.sh" "$@" | "$K" apply --server-side --field-manager=ok211 -f - 2>&1 >/dev/null | grep -v '^Warning: Kubernetes default value is insecure' || true; }

# x1_ksvc <ns> <ksvc> -> JSON: readiness, what reached the Deployment, PSA events, one request
x1_ksvc() {
  local ns="$1" ksvc="$2" rev dep ready code
  for _ in $(seq 1 60); do
    ready="$("$K" -n "$ns" get ksvc "$ksvc" -o json | jq -r '[.status.conditions[]? | select(.type=="Ready") | .status][0] // "Unknown"')"
    [ "$ready" = "Unknown" ] || break
    sleep 2
  done
  rev="$("$K" -n "$ns" get ksvc "$ksvc" -o jsonpath='{.status.latestCreatedRevisionName}')"
  dep="$("$K" -n "$ns" get deploy -l "serving.knative.dev/revision=$rev" -o json | jq -c '.items[0].spec.template.spec // {}
      | {pod: (.securityContext // {}), containers: [.containers[] | {name, securityContext: (.securityContext // {})}]}')"
  code="$("$K" -n ok211-load exec ok211-probe -- curl -sS -o /dev/null --max-time 30 -w '%{http_code}' \
    -H "Host: $ksvc.$ns.$KNATIVE_DOMAIN" http://kourier.kourier-system.svc.cluster.local/ || true)"
  jq -cn --arg ksvc "$ksvc" --arg rev "$rev" --argjson dep "$dep" --arg code "$code" \
    --argjson ks "$("$K" -n "$ns" get ksvc "$ksvc" -o json | jq -c '[.status.conditions[]? | {type, status, reason, message}]')" \
    --argjson rv "$("$K" -n "$ns" get revision "$rev" -o json | jq -c '[.status.conditions[]? | {type, status, reason, message}]')" \
    --argjson ev "$("$K" -n "$ns" get events -o json | jq -c --arg r "$rev" '[.items[] | select(.involvedObject.name | startswith($r)) | select(.reason == "FailedCreate") | .message] | unique')" \
    --argjson pods "$("$K" -n "$ns" get pods -l "serving.knative.dev/revision=$rev" -o json | jq '.items | length')" \
    '{ksvc: $ksvc, revision: $rev, ksvc_conditions: $ks, revision_conditions: $rv, deployment_pod_spec_security: $dep,
      replicaset_failedcreate: $ev, pods: $pods, request_via_kourier: $code}'
}

x1_run() { # x1_run <label>
  local label="$1"
  "$K" -n ok211-tenant-a delete ksvc podinfo-restricted podinfo-plain --ignore-not-found --wait=true >/dev/null 2>&1 || true
  apply_own security/x1-tenant-a.yaml
  sleep 30
  jq -cn --arg l "$label" --arg spd "$("$K" -n knative-serving get cm config-features -o jsonpath='{.data.secure-pod-defaults}')" \
    --argjson a "$(x1_ksvc ok211-tenant-a podinfo-restricted)" --argjson b "$(x1_ksvc ok211-tenant-a podinfo-plain)" \
    '{run: $l, secure_pod_defaults: (if $spd == "" then "disabled (release default, key unset)" else $spd end), services: [$a, $b]}'
}

x1() {
  local out a b psa
  out="$RAW/x1-pod-security-$(ok211::stamp).json"
  a="$(x1_run A)"
  # After run A, which creates ok211-tenant-a.
  psa="$(for ns in knative-serving knative-eventing kourier-system ok211-tenant-a; do
      "$K" get ns "$ns" -o json | jq -c '{namespace: .metadata.name, pod_security_labels: (.metadata.labels | with_entries(select(.key | test("pod-security"))))}'
    done | jq -s -c .)"
  "$K" -n knative-serving patch configmap config-features --type merge --patch-file "$SPIKE_ROOT/knative/patch-config-features-secure-on.yaml" >/dev/null
  b="$(x1_run B)"
  "$K" -n knative-serving patch configmap config-features --type merge --patch-file "$SPIKE_ROOT/knative/patch-config-features-secure-off.yaml" >/dev/null
  "$K" -n ok211-tenant-a delete ksvc podinfo-restricted podinfo-plain --ignore-not-found --wait=true >/dev/null
  jq -n --argjson psa "$psa" --argjson a "$a" --argjson b "$b" --arg ts "$(ok211::timestamp)" \
    '{id: "X1", timestamp_utc: $ts, namespaces: $psa, runs: [$a, $b],
      restore: "config-features secure-pod-defaults: disabled; services deleted; namespace ok211-tenant-a kept"}' > "$out"
  jq -c '{id: "X1", timestamp_utc, knative_version: "1.24.0", config: {namespace_psa: "restricted (enforce, warn, audit)"},
      runs: [], stats: {runs: [.runs[] | {run, secure_pod_defaults, services: [.services[] | {ksvc, ready: ([.ksvc_conditions[] | select(.type=="Ready") | .status][0]), pods, request_via_kourier, failedcreate: (.replicaset_failedcreate | length)}]}]},
      notes: "details in raw", raw: ["'"${out#"$SPIKE_ROOT/"}"'"]}' "$out" >> "$RAW/measurements.json"
  jq . "$out"
}

# x1-plain: run B again for podinfo-plain only and wait 90 s for its pod state
# (the first X1 run deleted the services after 30 s, before the pod settled).
x1_plain() {
  local out rev
  out="$RAW/x1-plain-enabled-$(ok211::stamp).json"
  "$K" -n knative-serving patch configmap config-features --type merge --patch-file "$SPIKE_ROOT/knative/patch-config-features-secure-on.yaml" >/dev/null
  "$K" -n ok211-tenant-a delete ksvc podinfo-plain --ignore-not-found --wait=true >/dev/null
  "$SCRIPT_DIR/render.sh" security/x1-tenant-a.yaml | yq 'select(.kind == "Namespace" or .metadata.name == "podinfo-plain")' \
    | "$K" apply --server-side --field-manager=ok211 -f - >/dev/null 2>&1
  local since; since="$(ok211::timestamp)"
  sleep 90
  rev="$("$K" -n ok211-tenant-a get ksvc podinfo-plain -o jsonpath='{.status.latestCreatedRevisionName}')"
  jq -n --arg since "$since" --arg rev "$rev" \
    --argjson pods "$("$K" -n ok211-tenant-a get pods -l "serving.knative.dev/revision=$rev" -o json | jq -c '[.items[] | {name: .metadata.name, phase: .status.phase,
        containers: [.status.containerStatuses[]? | {name, ready, state}]}]')" \
    --argjson ev "$("$K" -n ok211-tenant-a get events -o json | jq -c --arg s "$since" '[.items[] | select((.lastTimestamp // .eventTime // "") >= $s) | select(.type == "Warning") | {reason, message: .message[0:300]}] | unique')" \
    --argjson ks "$("$K" -n ok211-tenant-a get ksvc podinfo-plain -o json | jq -c '[.status.conditions[]? | {type, status, reason, message}]')" \
    '{id: "X1-plain-enabled", since: $since, revision: $rev, pods: $pods, warning_events_since: $ev, ksvc_conditions: $ks}' > "$out"
  "$K" -n knative-serving patch configmap config-features --type merge --patch-file "$SPIKE_ROOT/knative/patch-config-features-secure-off.yaml" >/dev/null
  "$K" -n ok211-tenant-a delete ksvc podinfo-plain --ignore-not-found --wait=true >/dev/null
  jq . "$out"
}

# x2: tenant RBAC (auth can-i as the tenant ServiceAccount), aggregated
# Knative ClusterRoles, Eventing auth features, EventPolicy CRD.
x2() {
  local out as checks="" ns verb res ans
  out="$RAW/x2-tenant-rbac-$(ok211::stamp).txt"
  apply_own security/x2-tenant-rbac.yaml
  as="system:serviceaccount:ok211-tenant-a:tenant-a-dev"
  {
    echo "# X2 $(ok211::timestamp) — kubectl auth can-i --as=$as"
    printf '%-10s %-55s %-18s %s\n' verb resource namespace answer
    while read -r verb res ns; do
      ans="$("$K" auth can-i "$verb" "$res" ${ns:+-n "$ns"} --as="$as" 2>/dev/null || true)"
      printf '%-10s %-55s %-18s %s\n' "$verb" "$res" "${ns:-<cluster>}" "$ans"
      checks="$checks$verb|$res|${ns:-cluster}|$ans;"
    done <<'CHECKS'
create services.serving.knative.dev ok211-tenant-a
update services.serving.knative.dev ok211-tenant-a
create services.serving.knative.dev ok211-serving
list services.serving.knative.dev ok211-serving
get configmaps/config-network knative-serving
update configmaps/config-network knative-serving
update configmaps/config-autoscaler knative-serving
create domainmappings.serving.knative.dev ok211-tenant-a
create clusterdomainclaims.networking.internal.knative.dev
create brokers.eventing.knative.dev ok211-tenant-a
create triggers.eventing.knative.dev ok211-tenant-a
create pingsources.sources.knative.dev ok211-tenant-a
create apiserversources.sources.knative.dev ok211-tenant-a
create eventpolicies.eventing.knative.dev ok211-tenant-a
create triggers.eventing.knative.dev ok211-events
create ingresses.networking.internal.knative.dev ok211-tenant-a
create podautoscalers.autoscaling.internal.knative.dev ok211-tenant-a
get secrets ok211-tenant-a
CHECKS
    echo; echo "## Knative ClusterRoles aggregated into admin / edit / view"
    for r in admin edit view; do
      echo "### aggregate-to-$r: $("$K" get clusterroles -l "rbac.authorization.k8s.io/aggregate-to-$r=true" -o name | grep -iE 'knative|serving|eventing|source|messaging|flows' | sed 's#clusterrole.rbac.authorization.k8s.io/##' | tr '\n' ' ')"
    done
    echo; echo "## Eventing config-features (live data; empty = release default)"
    "$K" -n knative-eventing get cm config-features -o json | jq -c '.data | with_entries(select(.key | test("authentication-oidc|default-authorization-mode|transport-encryption|cross-namespace-event-links")))'
    echo "## EventPolicy CRD"; "$K" get crd eventpolicies.eventing.knative.dev -o json | jq -c '{name: .metadata.name, scope: .spec.scope, versions: [.spec.versions[].name]}'
    "$K" explain eventpolicies.spec --api-version=eventing.knative.dev/v1alpha1 2>/dev/null | sed -n '1,25p' || true
  } > "$out"
  jq -cn --arg ts "$(ok211::timestamp)" --arg c "$checks" --arg raw "${out#"$SPIKE_ROOT/"}" \
    '{id: "X2", timestamp_utc: $ts, knative_version: "1.24.0", config: {identity: "ServiceAccount ok211-tenant-a/tenant-a-dev, RoleBinding to ClusterRole edit"}, runs: [],
      stats: {can_i: ($c | split(";") | map(select(length > 0) | split("|") | {verb: .[0], resource: .[1], namespace: .[2], answer: .[3]}))},
      notes: "auth can-i via impersonation", raw: [$raw]}' >> "$RAW/measurements.json"
  cat "$out"
}

# x3: NetworkPolicy isolation in ok211-tenant-b. Steps: none, deny, deny +
# allow knative-serving, + allow kourier-system. Per step: warm request to
# tb-warm, cold request to tb-cold from zero, SKS modes; in steps 3 and 4 a
# 50-connection burst against tb-warm (pushes the SKS to Serve mode).
x3_req() { # x3_req <ksvc> -> "code time_total"
  "$K" -n ok211-load exec ok211-probe -- curl -sS -o /dev/null --max-time 60 -w '%{http_code} %{time_total}' \
    -H "Host: $1.ok211-tenant-b.$KNATIVE_DOMAIN" http://kourier.kourier-system.svc.cluster.local/ 2>/dev/null || echo "000 60"
}
x3_zero() { # wait up to 150 s for tb-cold at zero; prints the wait
  local rev t0; rev="$("$K" -n ok211-tenant-b get ksvc tb-cold -o jsonpath='{.status.latestCreatedRevisionName}')"; t0="$(date -u +%s)"
  while [ $(( $(date -u +%s) - t0 )) -lt 150 ]; do
    [ "$("$K" -n ok211-tenant-b get pods -l "serving.knative.dev/revision=$rev" -o json | jq '.items | length')" = 0 ] && { sleep 10; echo "zero after $(( $(date -u +%s) - t0 - 10 )) s"; return 0; }
    sleep 3
  done
  echo "not at zero after 150 s"
}
x3_step() { # x3_step <label> <burst 0|1>
  local label="$1" warm cold z modes burst="null"
  sleep 5
  warm="$(x3_req tb-warm)"
  z="$(x3_zero)"
  cold="$(x3_req tb-cold)"
  if [ "$2" = 1 ]; then
    ( for _ in $(seq 1 30); do "$K" -n ok211-tenant-b get sks -o json | jq -r '[.items[] | "\(.metadata.name)=\(.spec.mode)"] | join(" ")'; sleep 2; done ) > "$RAW/x3-sks-$label.txt" &
    local sp=$!
    OK211_NS=ok211-tenant-b "$SCRIPT_DIR/measure-serving.sh" fortio "X3-burst-$label" tb-warm 0 50 20s > "$RAW/x3-burst-$label.json" 2> "$RAW/x3-burst-$label.log" || true
    wait "$sp" || true
    burst="$(jq -c '{codes, count, p99_ms}' "$RAW/x3-burst-$label.json" 2>/dev/null || echo null)"
  fi
  modes="$("$K" -n ok211-tenant-b get sks -o json | jq -c '[.items[] | {(.metadata.name): .spec.mode}] | add')"
  jq -cn --arg l "$label" --arg w "$warm" --arg c "$cold" --arg z "$z" --argjson m "$modes" --argjson b "$burst" \
    --argjson np "$("$K" -n ok211-tenant-b get networkpolicy -o json | jq -c '[.items[].metadata.name]')" \
    --arg sksmodes "$( [ -f "$RAW/x3-sks-$label.txt" ] && sort "$RAW/x3-sks-$label.txt" | uniq -c | tr -s ' ' | tr '\n' ';' || echo "")" \
    '{step: $l, policies: $np, warm_tb_warm: $w, cold_tb_cold: $c, zero_wait: $z, sks_mode_after: $m, burst_tb_warm: $b, sks_modes_during_burst: $sksmodes}'
}
x3() {
  local out s0 s1 s2 s3
  out="$RAW/x3-networkpolicy-$(ok211::stamp).json"
  "$K" -n ok211-tenant-b delete networkpolicy --all --ignore-not-found >/dev/null 2>&1 || true
  apply_own security/x3-tenant-b.yaml
  "$K" -n ok211-tenant-b wait --for=condition=Ready ksvc/tb-cold ksvc/tb-warm --timeout=300s >/dev/null
  s0="$(x3_step 0-none 0)"
  apply_own security/x3-deny.yaml; s1="$(x3_step 1-deny 0)"
  apply_own security/x3-allow-serving.yaml; s2="$(x3_step 2-allow-serving 1)"
  apply_own security/x3-allow-kourier.yaml; s3="$(x3_step 3-allow-kourier 1)"
  jq -n --arg ts "$(ok211::timestamp)" --argjson a "$s0" --argjson b "$s1" --argjson c "$s2" --argjson d "$s3" \
    '{id: "X3", timestamp_utc: $ts, steps: [$a, $b, $c, $d],
      notes: "requests from ok211-probe through kourier; warm = tb-warm (min-scale 1), cold = tb-cold from zero; policies stay in place (namespace-local)"}' > "$out"
  jq -c '{id, timestamp_utc, knative_version: "1.24.0", config: {namespace: "ok211-tenant-b", enforcement: "K3s embedded kube-router NetworkPolicy controller"}, runs: .steps, stats: {steps: [.steps[] | {step, warm_tb_warm, cold_tb_cold, burst: .burst_tb_warm.codes}]}, notes, raw: ["'"${out#"$SPIKE_ROOT/"}"'"]}' "$out" >> "$RAW/measurements.json"
  jq . "$out"
}

# x3-recheck: deny only, settled for 60 s: direct pod access from the probe,
# warm request, two cold starts; then the allows are re-applied.
x3_recheck() {
  local out ip direct warm c1 c2 z1 z2 t
  out="$RAW/x3-recheck-$(ok211::stamp).json"
  "$K" -n ok211-tenant-b delete networkpolicy allow-knative-serving allow-kourier-gateway --ignore-not-found >/dev/null
  t="$(ok211::timestamp)"; sleep 60
  ip="$("$K" -n ok211-tenant-b get pods -l serving.knative.dev/service=tb-warm -o jsonpath='{.items[0].status.podIP}')"
  direct="$("$K" -n ok211-load exec ok211-probe -- curl -sS -o /dev/null --max-time 5 -w '%{http_code}' "http://$ip:8012/" 2>&1 || true)"
  warm="$(x3_req tb-warm)"
  z1="$(x3_zero)"; c1="$(x3_req tb-cold)"
  z2="$(x3_zero)"; c2="$(x3_req tb-cold)"
  local act; act="$("$K" -n knative-serving logs deploy/activator --since=5m 2>/dev/null | grep -iE 'ok211-tenant-b' | grep -iE 'error|refused|timeout|probe' | tail -5 | cut -c1-300 || true)"
  apply_own security/x3-allow-serving.yaml security/x3-allow-kourier.yaml
  jq -n --arg t "$t" --arg ip "$ip" --arg d "$direct" --arg w "$warm" --arg c1 "$c1" --arg c2 "$c2" --arg z1 "$z1" --arg z2 "$z2" --arg act "$act" \
    --arg ts "$(ok211::timestamp)" \
    '{id: "X3-recheck", timestamp_utc: $ts, deny_only_since: $t, settle_s: 60, tb_warm_pod_ip: $ip,
      direct_probe_to_pod_8012: $d, warm_tb_warm: $w, cold_1: $c1, zero_wait_1: $z1, cold_2: $c2, zero_wait_2: $z2,
      activator_log_lines: ($act | split("\n")), restored: "allow-knative-serving and allow-kourier-gateway re-applied"}' > "$out"
  jq -c '{id, timestamp_utc, knative_version: "1.24.0", config: {policies: "default-deny-ingress only, settled 60 s"}, runs: [], stats: {direct_probe_to_pod_8012, warm_tb_warm, cold_1, cold_2}, notes: "follow-up to X3 step 1", raw: ["'"${out#"$SPIKE_ROOT/"}"'"]}' "$out" >> "$RAW/measurements.json"
  jq . "$out"
}

# x3-newpod [max_s]: deny only; a cold start creates a new pod; then a
# request every 5 s (which keeps the pod alive) until the first non-200 or
# max_s, to see when the policy starts to apply to the new pod. Allows
# re-applied at the end.
x3_newpod() {
  local max="${1:-360}" out rows="" r pod t z t0
  out="$RAW/x3-newpod-$(ok211::stamp).json"
  "$K" -n ok211-tenant-b delete networkpolicy allow-knative-serving allow-kourier-gateway --ignore-not-found >/dev/null
  sleep 60
  z="$(x3_zero)"
  t="$(ok211::timestamp)"; t0="$(date -u +%s)"
  while [ $(( $(date -u +%s) - t0 )) -le "$max" ]; do
    r="$(x3_req tb-cold)"
    pod="$("$K" -n ok211-tenant-b get pods -l serving.knative.dev/service=tb-cold -o json | jq -r '[.items[] | select(.metadata.deletionTimestamp == null)][0] | "\(.metadata.name) \(.status.podIP) \(.metadata.creationTimestamp)"')"
    rows="$rows$(date -u +%FT%TZ)|$r|$pod;"
    case "$r" in 200\ *) : ;; *) break ;; esac
    sleep 5
  done
  apply_own security/x3-allow-serving.yaml security/x3-allow-kourier.yaml
  jq -n --arg t "$t" --arg z "$z" --arg rows "$rows" --arg ts "$(ok211::timestamp)" --argjson max "$max" \
    '{id: "X3-newpod", timestamp_utc: $ts, policies: "default-deny-ingress only (settled 60 s)", zero_wait: $z, first_request: $t, max_s: $max,
      requests: ($rows | split(";") | map(select(length > 0) | split("|") | {utc: .[0], result: .[1], pod: .[2]}))}' > "$out"
  jq -c '{id, timestamp_utc, knative_version: "1.24.0", config: {policies, max_s}, runs: .requests,
      stats: {requests: (.requests | length), codes: (.requests | map(.result | split(" ")[0]) | group_by(.) | map({(.[0]): length}) | add),
              first_non_200: ([.requests[] | select(.result | startswith("200") | not)][0] // null), first: .requests[0].utc, pod: .requests[0].pod},
      notes: "requests to tb-cold every 5 s after a cold start under default deny, until the first non-200", raw: ["'"${out#"$SPIKE_ROOT/"}"'"]}' "$out" >> "$RAW/measurements.json"
  jq -r '.requests[] | "\(.utc) \(.result) \(.pod)"' "$out"
}

# x3-samepod [max_s]: deny only; the tb-warm pod (min-scale 1) is replaced by
# deleting it; then a request every 5 s to tb-warm until the first non-200 or
# max_s. The pod name is logged, so a pod change shows. Allows re-applied.
x3_samepod() {
  local max="${1:-600}" out rows="" r pod t0 old
  out="$RAW/x3-samepod-$(ok211::stamp).json"
  "$K" -n ok211-tenant-b delete networkpolicy allow-knative-serving allow-kourier-gateway --ignore-not-found >/dev/null
  sleep 60
  old="$("$K" -n ok211-tenant-b get pods -l serving.knative.dev/service=tb-warm -o jsonpath='{.items[0].metadata.name}')"
  local before; before="$(x3_req tb-warm)"
  "$K" -n ok211-tenant-b delete pod "$old" --wait=false >/dev/null
  "$K" -n ok211-tenant-b wait --for=condition=Ready pod -l serving.knative.dev/service=tb-warm --timeout=120s >/dev/null 2>&1 || true
  t0="$(date -u +%s)"
  while [ $(( $(date -u +%s) - t0 )) -le "$max" ]; do
    r="$(x3_req tb-warm)"
    pod="$("$K" -n ok211-tenant-b get pods -l serving.knative.dev/service=tb-warm -o json | jq -r '[.items[] | select(.metadata.deletionTimestamp == null)][0] | "\(.metadata.name) \(.status.podIP) \(.metadata.creationTimestamp)"')"
    rows="$rows$(date -u +%FT%TZ)|$r|$pod;"
    case "$r" in 200\ *) : ;; *) break ;; esac
    sleep 5
  done
  apply_own security/x3-allow-serving.yaml security/x3-allow-kourier.yaml
  jq -n --arg old "$old" --arg before "$before" --arg rows "$rows" --arg ts "$(ok211::timestamp)" --argjson max "$max" \
    '{id: "X3-samepod", timestamp_utc: $ts, policies: "default-deny-ingress only (settled 60 s)", old_pod: $old, request_to_old_pod: $before, max_s: $max,
      requests: ($rows | split(";") | map(select(length > 0) | split("|") | {utc: .[0], result: .[1], pod: .[2]}))}' > "$out"
  jq -c '{id, timestamp_utc, knative_version: "1.24.0", config: {policies, max_s}, runs: .requests,
      stats: {request_to_old_pod, requests: (.requests | length), codes: (.requests | map(.result | split(" ")[0]) | group_by(.) | map({(.[0]): length}) | add),
              pods_seen: (.requests | map(.pod | split(" ")[0]) | unique), first: .requests[0].utc, first_non_200: ([.requests[] | select(.result | startswith("200") | not)][0] // null)},
      notes: "tb-warm (min-scale 1) pod replaced under default deny; request every 5 s until the first non-200", raw: ["'"${out#"$SPIKE_ROOT/"}"'"]}' "$out" >> "$RAW/measurements.json"
  jq -r '.request_to_old_pod as $b | "old pod: \($b)", (.requests[] | "\(.utc) \(.result) \(.pod)")' "$out"
}

# x4-webhook: Serving webhook scaled to 0 (the HPA does not scale up from 0);
# create, delete and config change attempts; data path check; restore to 1.
# Run as the last experiment of the phase, without measurements or PingSource.
x4_webhook() {
  local out t0 r_create r_delete r_cfg r_data r_ctrl a_create a_delete
  out="$RAW/x4-webhook-down-$(ok211::stamp).txt"
  "$K" -n ok211-events delete pingsource ok211-ping --ignore-not-found >/dev/null
  t0="$(ok211::timestamp)"
  "$K" -n knative-serving scale deploy/webhook --replicas=0 >/dev/null
  "$K" -n knative-serving wait --for=delete pod -l app=webhook --timeout=120s >/dev/null 2>&1 || true
  sleep 5
  r_create="$("$SCRIPT_DIR/render.sh" security/x4-probe-ksvc.yaml | "$K" apply --server-side --field-manager=ok211 -f - 2>&1 | grep -v '^Warning' | cut -c1-400 || true)"
  r_delete="$("$K" -n ok211-serving delete ksvc podinfo-private --wait=false 2>&1 | cut -c1-400 || true)"
  r_cfg="$("$K" -n knative-serving patch configmap config-autoscaler --type merge -p '{"data":{"ok211-x4-test":"1"}}' 2>&1 | cut -c1-400 || true)"
  r_data="$("$K" -n ok211-load exec ok211-probe -- curl -sS -o /dev/null --max-time 60 -w '%{http_code} %{time_total}' \
    -H "Host: podinfo.ok211-serving.$KNATIVE_DOMAIN" http://kourier.kourier-system.svc.cluster.local/ 2>&1 || true)"
  sleep 20
  r_ctrl="$("$K" -n knative-serving logs deploy/controller --since=2m 2>/dev/null | grep -iE 'webhook|failed calling|connection refused|no endpoints' | tail -3 | cut -c1-300 || true)"
  {
    echo "# X4 webhook down $(ok211::timestamp) (scaled to 0 at $t0; PingSource ok211-ping deleted before)"
    echo "## webhook deployment"; "$K" -n knative-serving get deploy webhook; "$K" -n knative-serving get hpa webhook 2>&1 | tail -2
    echo "## create ksvc x4-probe"; echo "$r_create"
    echo "## delete ksvc podinfo-private"; echo "$r_delete"
    echo "## patch config-autoscaler"; echo "$r_cfg"
    echo "## data path: existing ksvc podinfo via kourier"; echo "$r_data"
    echo "## controller log lines"; echo "$r_ctrl"
  } > "$out"
  "$K" -n knative-serving scale deploy/webhook --replicas=1 >/dev/null
  "$K" -n knative-serving wait --for=condition=Available deploy/webhook --timeout=300s >/dev/null
  sleep 10
  a_create="$("$SCRIPT_DIR/render.sh" security/x4-probe-ksvc.yaml | "$K" apply --server-side --field-manager=ok211 -f - 2>&1 | grep -v '^Warning' || true)"
  "$K" -n ok211-serving wait --for=condition=Ready ksvc/x4-probe --timeout=300s >/dev/null 2>&1 || true
  local a_ready; a_ready="$("$K" -n ok211-serving get ksvc x4-probe -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>&1 || true)"
  a_delete="$("$K" -n ok211-serving delete ksvc x4-probe --wait=true 2>&1 || true)"
  {
    echo "## restore $(ok211::timestamp): webhook replicas 1, Available"
    echo "## create ksvc x4-probe after restore"; echo "$a_create"; echo "x4-probe Ready: $a_ready"
    echo "## delete x4-probe after restore"; echo "$a_delete"
    echo "## podinfo-private still present? $("$K" -n ok211-serving get ksvc podinfo-private -o name 2>&1)"
    echo "## config-autoscaler key ok211-x4-test present: $("$K" -n knative-serving get cm config-autoscaler -o json | jq '.data | has("ok211-x4-test")')"
  } >> "$out"
  jq -cn --arg ts "$(ok211::timestamp)" --arg c "$r_create" --arg d "$r_delete" --arg cfg "$r_cfg" --arg data "$r_data" --arg raw "${out#"$SPIKE_ROOT/"}" \
    '{id: "X4-webhook-down", timestamp_utc: $ts, knative_version: "1.24.0", config: {webhook_replicas: 0}, runs: [],
      stats: {create_ksvc: $c, delete_ksvc: $d, patch_config_autoscaler: $cfg, data_path_existing_ksvc: $data},
      notes: "restored to 1 replica; PingSource ok211-ping deleted beforehand (BRIEF)", raw: [$raw]}' >> "$RAW/measurements.json"
  cat "$out"
}

case "${1:-}" in
  x1) x1 ;;
  x4-webhook) x4_webhook ;;
  x3-samepod) x3_samepod "${2:-600}" ;;
  x3-newpod) x3_newpod "${2:-360}" ;;
  x3-recheck) x3_recheck ;;
  x3) x3 ;;
  x2) x2 ;;
  x1-plain) x1_plain ;;
  *) ok211::die "usage: $0 x1|x1-plain|x2|x3|x3-recheck|x3-newpod|x3-samepod|x4-webhook" 2 ;;
esac
