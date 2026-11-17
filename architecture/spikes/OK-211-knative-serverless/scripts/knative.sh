#!/usr/bin/env bash
#
# OK-211 — install, verify and upgrade Knative from the checksum-verified local
# release manifests (BRIEF B8 "Release-Manifeste und eigene Overrides", B9 Phases 3-4).
#
# Usage: scripts/knative.sh install <line>|verify|upgrade <line>|dry-run <line>|post-install <line>
#   <line>  1.23 | 1.24
#
# Rules this script implements:
# - Release YAMLs only from .local/manifests/<line>/, each checked against its
#   pin in versions.env immediately before it is applied (B4 rule 10).
# - Release YAMLs are applied server-side with field manager knative-release.
#   Conflicts are never overridden with --force-conflicts: the apply fails and
#   the conflict is reported (B8).
# - Fields owned at runtime by a controller are left to it (CP3 decisions B,
#   B2, B3, see derive_apply_set): webhook rules, aggregated ClusterRole
#   rules, pingsource-mt-adapter replicas and controller-filled env values.
# - Own values only as merge patches from knative/*.yaml (never full ConfigMaps),
#   so a later release apply does not remove them.
# - Post-install Jobs (generateName) are created with `kubectl create`, the
#   other objects of the same file with `apply`; a Job is only created when no
#   Job of the same kind is already Complete for the target version.
# - Every step writes a UTC start/end mark to $STEP_LOG (upgrade-steps.log for U1).
#
# The caller (make) runs the guard with --node first.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
ok211::load_versions

K="${KUBECTL:-$SPIKE_ROOT/.local/bin/kubectl}"
FM=knative-release
STEP_LOG="${STEP_LOG:-$SPIKE_ROOT/.local/knative-steps.log}"
# Image pulls over a slow link take minutes (Phase 2: ≈ 150 KB/s from dl.k8s.io).
WAIT="${KNATIVE_WAIT:-900s}"

mark() { printf '%s\t%s\t%s\n' "$(ok211::timestamp)" "$1" "$2" >> "$STEP_LOG"; }

line_ok() {
  case "$1" in 1.23|1.24) : ;; *) ok211::die "unknown line '$1' (expected 1.23 or 1.24)" 2 ;; esac
}

# manifest <line> <asset> -> path, after verifying the pin.
manifest() {
  local line="$1" asset="$2" key pin f got
  f="$SPIKE_ROOT/.local/manifests/$line/$asset"
  [ -f "$f" ] || ok211::die "missing $line/$asset; run 'make manifests-fetch VERSION=$line'" 2
  key="MANIFEST_SHA256_$(printf '%s' "$line" | tr 'a-z.-' 'A-Z__')_$(printf '%s' "${asset%.yaml}" | tr 'a-z.-' 'A-Z__')"
  pin="${!key:-}"
  got="$(shasum -a 256 "$f" | awk '{print $1}')"
  [ -n "$pin" ] && [ "$got" = "$pin" ] || ok211::die "checksum of $line/$asset is $got, pin $key=${pin:-<none>} (STOP-4)" 1
  printf '%s\n' "$f"
}

# derive_apply_set <line> <asset> <pinned file> -> file to apply.
# Some fields of the release objects are owned at runtime by a controller, so
# every later server-side apply of the release value conflicts with it
# (Phase 4, CP3 decisions B and B2). Two rules, nothing else:
#   1. `.webhooks[].rules` of Mutating/ValidatingWebhookConfigurations: owned by
#      Knative's webhooks (`webhook`, `channel_controller`). Eventing and IMC
#      already ship them without rules; serving-core ships static rules.
#   2. `.rules` of ClusterRoles with an `aggregationRule`: owned by Kubernetes'
#      `clusterrole-aggregation-controller`. eventing-core ships `rules: []`.
#   3. Deployment knative-eventing/pingsource-mt-adapter: `.spec.replicas` and
#      the values of K_OBSERVABILITY_CONFIG, K_LOGGING_CONFIG,
#      K_LEADER_ELECTION_CONFIG, K_NO_SHUTDOWN_AFTER, which the manifest itself
#      marks as filled by the ping source controller ("DO NOT MODIFY").
# The result is checked against an independent jq implementation of the same
# rules, so the derived file differs from the pinned one in exactly that.
# Files where neither rule removes anything are applied unchanged.
derive_apply_set() {
  local line="$1" asset="$2" f="$3" d wh cr pa pe nw nc np sum
  wh='select(.kind == "MutatingWebhookConfiguration" or .kind == "ValidatingWebhookConfiguration")'
  cr='select(.kind == "ClusterRole" and has("aggregationRule"))'
  pa='select(.kind == "Deployment" and .metadata.namespace == "knative-eventing" and .metadata.name == "pingsource-mt-adapter")'
  pe='K_OBSERVABILITY_CONFIG K_LOGGING_CONFIG K_LEADER_ELECTION_CONFIG K_NO_SHUTDOWN_AFTER'
  nw="$(yq -N "$wh | [.webhooks[] | select(has(\"rules\"))] | length" "$f" | awk '{s+=$1} END{print s+0}')"
  nc="$(yq -N "$cr | [select(has(\"rules\"))] | length" "$f" | awk '{s+=$1} END{print s+0}')"
  np="$(yq -N "$pa | [1] | length" "$f" | awk '{s+=$1} END{print s+0}')"
  if [ "$nw" -eq 0 ] && [ "$nc" -eq 0 ] && [ "$np" -eq 0 ]; then printf '%s\n' "$f"; return 0; fi
  d="$SPIKE_ROOT/.local/manifests/$line/derived/$asset"
  mkdir -p "$(dirname "$d")"
  yq "($wh | .webhooks[]) |= del(.rules) | ($cr) |= del(.rules)
      | ($pa) |= del(.spec.replicas)
      | ($pa | .spec.template.spec.containers[].env[] | select(.name as \$n | \"$pe\" | split(\" \") | contains([\$n]))) |= del(.value)" "$f" > "$d"
  # shellcheck disable=SC2016  # jq program
  jq -e -n --arg pe "$pe" --slurpfile a <(yq -o=json -I=0 '.' "$f") --slurpfile b <(yq -o=json -I=0 '.' "$d") '
    ($pe | split(" ")) as $names
    | ($a | map(if (.kind == "MutatingWebhookConfiguration" or .kind == "ValidatingWebhookConfiguration")
                then .webhooks |= map(del(.rules))
              elif (.kind == "ClusterRole" and has("aggregationRule")) then del(.rules)
              elif (.kind == "Deployment" and .metadata.namespace == "knative-eventing" and .metadata.name == "pingsource-mt-adapter")
                then del(.spec.replicas)
                  | .spec.template.spec.containers |= map(.env |= map(if (.name as $n | $names | index($n)) then del(.value) else . end))
              else . end)) == $b' >/dev/null \
    || ok211::die "derived $line/$asset differs from the pinned file in more than the derivation rules" 1
  sum="$(shasum -a 256 "$d" | awk '{print $1}')"
  ok211::info "derived $line/$asset: rules removed from $nw webhook(s), $nc aggregated ClusterRole(s); pingsource-mt-adapter fields removed: $np; sha256 $sum"
  mark "info" "derived $line/$asset: webhook rules ($nw), aggregated ClusterRole rules ($nc), pingsource-mt-adapter fields ($np), sha256 $sum"
  printf '%s\n' "$d"
}

apply_release() { # apply_release <line> <asset>
  local f; f="$(manifest "$1" "$2")"
  f="$(derive_apply_set "$1" "$2" "$f")"
  mark "start" "apply $1/$2"
  ok211::info "apply --server-side --field-manager=$FM $1/$2"
  if ! "$K" apply --server-side --field-manager="$FM" -f "$f" > "$SPIKE_ROOT/.local/apply-$2.log" 2>&1; then
    grep -iE 'conflict|error' "$SPIKE_ROOT/.local/apply-$2.log" | head -20 >&2
    mark "fail" "apply $1/$2"
    ok211::die "server-side apply of $1/$2 failed (conflicts are not forced, B8); log: .local/apply-$2.log" 1
  fi
  mark "end" "apply $1/$2"
}

wait_crds() { # wait_crds <file>
  local crds=() n
  while IFS= read -r n; do crds+=("crd/$n"); done < <(yq -N 'select(.kind=="CustomResourceDefinition") | .metadata.name' "$1")
  "$K" wait --for=condition=Established --timeout="$WAIT" "${crds[@]}" >/dev/null
}

wait_deploy() { # wait_deploy <ns> <deployment...>
  local ns="$1"; shift
  local d
  for d in "$@"; do
    mark "start" "wait $ns/$d Available"
    "$K" -n "$ns" wait --for=condition=Available --timeout="$WAIT" "deployment/$d" >/dev/null
    mark "end" "wait $ns/$d Available"
  done
}

wait_all_deploy() { # wait_all_deploy <ns...>
  local ns
  for ns in "$@"; do
    "$K" -n "$ns" wait --for=condition=Available --timeout="$WAIT" deployment --all >/dev/null
  done
}

patch_cm() { # patch_cm <ns> <configmap> <patch file>
  mark "start" "patch $1/$2"
  "$K" -n "$1" patch configmap "$2" --type merge --patch-file "$SPIKE_ROOT/$3" >/dev/null
  mark "end" "patch $1/$2"
  ok211::info "patched $1/configmap/$2 from $3"
}

apply_overrides() {
  patch_cm knative-serving config-network knative/patch-config-network.yaml
  patch_cm knative-serving config-domain knative/patch-config-domain.yaml
  # Optional overrides: only applied when the file exists (documented deviations).
  [ -f "$SPIKE_ROOT/knative/patch-config-autoscaler.yaml" ] \
    && patch_cm knative-serving config-autoscaler knative/patch-config-autoscaler.yaml
  # N2 active: the release apply resets the kourier Service; re-apply the patch.
  if [ -f "$SPIKE_ROOT/.local/n2-active" ]; then
    "$K" -n kourier-system patch service kourier --type merge --patch-file "$SPIKE_ROOT/knative/patch-kourier-clusterip.yaml" >/dev/null
    ok211::info "N2 active: re-applied knative/patch-kourier-clusterip.yaml"
  fi
  return 0
}

# post_install <line>: run the post-install Jobs of both projects for <line>.
post_install() {
  local line="$1"
  run_jobs "$(manifest "$line" serving-post-install-jobs.yaml)" knative-serving
  run_jobs "$(manifest "$line" eventing-post-install.yaml)" knative-eventing
}

# run_jobs <file> <ns>: non-Job objects via apply, each Job via create, unless
# a Job with the same generateName prefix and the file's version label is
# already Complete.
run_jobs() {
  local f="$1" ns="$2" tmp prefix ver n i
  tmp="$SPIKE_ROOT/.local/tmp/postinstall-$(ok211::stamp)"; mkdir -p "$tmp"
  yq 'select(.kind != "Job" and .kind != null)' "$f" > "$tmp/other.yaml"
  if [ -s "$tmp/other.yaml" ]; then
    mark "start" "apply non-Job objects of $(basename "$f")"
    "$K" apply --server-side --field-manager="$FM" -f "$tmp/other.yaml" >/dev/null
    mark "end" "apply non-Job objects of $(basename "$f")"
  fi
  # eval-all (ea): the index runs over the Jobs of the whole file, not per document.
  n="$(yq ea -N '[select(.kind == "Job")] | length' "$f")"
  i=0
  while [ "$i" -lt "$n" ]; do
    yq ea -N "[select(.kind == \"Job\")] | .[$i]" "$f" > "$tmp/job-$i.yaml"
    prefix="$(yq -N '.metadata.generateName' "$tmp/job-$i.yaml")"
    ver="$(yq -N '.metadata.labels["app.kubernetes.io/version"]' "$tmp/job-$i.yaml")"
    done_jobs="$("$K" -n "$ns" get jobs -l "app.kubernetes.io/version=$ver" -o json \
      | jq -r --arg p "$prefix" '[.items[] | select(.metadata.name | startswith($p))
          | select(any(.status.conditions[]?; .type == "Complete" and .status == "True")) | .metadata.name] | join(",")')"
    if [ -n "$done_jobs" ]; then
      ok211::info "post-install $prefix (version $ver) already Complete: $done_jobs — not created again"
    else
      mark "start" "create Job ${prefix}* ($ver)"
      name="$("$K" create -f "$tmp/job-$i.yaml" -o jsonpath='{.metadata.name}')"
      "$K" -n "$ns" wait --for=condition=Complete --timeout="$WAIT" "job/$name" >/dev/null
      mark "end" "create Job $name ($ver) Complete"
      ok211::ok "post-install Job $ns/$name Complete"
    fi
    i=$((i + 1))
  done
  rm -rf "$tmp"
}

install_line() {
  local line="$1"
  mark "start" "knative-install $line"
  # 1. Serving CRDs and core; the config webhook (failurePolicy Fail) must be
  #    Available before any config-* ConfigMap is patched.
  apply_release "$line" serving-crds.yaml
  wait_crds "$(manifest "$line" serving-crds.yaml)"
  apply_release "$line" serving-core.yaml
  wait_deploy knative-serving webhook controller
  # 2. Kourier, then the ingress class.
  apply_release "$line" kourier.yaml
  # 3. Overrides (ingress class, domain) as merge patches.
  apply_overrides
  # 4. Eventing.
  apply_release "$line" eventing-crds.yaml
  wait_crds "$(manifest "$line" eventing-crds.yaml)"
  apply_release "$line" eventing-core.yaml
  wait_deploy knative-eventing eventing-webhook
  apply_release "$line" in-memory-channel.yaml
  apply_release "$line" mt-channel-broker.yaml
  wait_all_deploy knative-serving kourier-system knative-eventing
  mark "end" "knative-install $line"
  ok211::ok "Knative $line installed (serving, kourier, eventing, imc, mt-broker)"
}

# upgrade_line <to>: one minor step, in the order of the upgrade docs and B9 U1:
# CRDs of both projects first, then Serving core, Kourier, Eventing core and
# channel/broker, overrides re-checked, wait until every deployment carries the
# new version label and is Available, then post-install Jobs.
upgrade_line() {
  local to="$1" sk="SERVING_${1/./_}" ek="EVENTING_${1/./_}" want_serving want_eventing ns
  want_serving="${!sk#knative-v}"
  want_eventing="${!ek#knative-v}"
  mark "start" "knative-upgrade to $to"
  apply_release "$to" serving-crds.yaml
  apply_release "$to" eventing-crds.yaml
  wait_crds "$(manifest "$to" serving-crds.yaml)"
  wait_crds "$(manifest "$to" eventing-crds.yaml)"
  apply_release "$to" serving-core.yaml
  wait_version knative-serving "$want_serving" webhook controller activator autoscaler
  apply_release "$to" kourier.yaml
  wait_version knative-serving "$want_serving" net-kourier-controller
  wait_version kourier-system "$want_serving" 3scale-kourier-gateway
  apply_overrides
  apply_release "$to" eventing-core.yaml
  wait_version knative-eventing "$want_eventing" eventing-webhook eventing-controller
  apply_release "$to" in-memory-channel.yaml
  apply_release "$to" mt-channel-broker.yaml
  for ns in knative-serving kourier-system knative-eventing; do
    wait_all_version "$ns"
  done
  mark "end" "all deployments on $to Available"
  post_install "$to"
  mark "end" "knative-upgrade to $to"
  ok211::ok "Knative upgraded to $to"
}

# wait_version <ns> <version> <deployment...>: rollout of the new version done.
wait_version() {
  local ns="$1" want="$2" d; shift 2
  for d in "$@"; do
    mark "start" "rollout $ns/$d -> $want"
    for _ in $(seq 1 180); do
      got="$("$K" -n "$ns" get deploy "$d" -o jsonpath='{.metadata.labels.app\.kubernetes\.io/version}')"
      [ "${got#v}" = "$want" ] && break
      sleep 2
    done
    "$K" -n "$ns" rollout status "deployment/$d" --timeout="$WAIT" >/dev/null
    mark "end" "rollout $ns/$d -> $want"
  done
}

wait_all_version() {
  local ns="$1" d
  while IFS= read -r d; do
    [ -n "$d" ] || continue
    "$K" -n "$ns" rollout status "deployment/$d" --timeout="$WAIT" >/dev/null
  done < <("$K" -n "$ns" get deploy -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')
}

# dry_run <line>: server-side dry run of every release file of <line> in
# upgrade order, as the apply would send it (pin check and derivation
# included). Changes nothing; lists every conflict instead of stopping at the
# first file. Exit 1 if any file would fail.
dry_run() {
  local line="$1" a f rc=0 log
  log="$SPIKE_ROOT/.local/dry-run-$line.log"; : > "$log"
  for a in serving-crds.yaml eventing-crds.yaml serving-core.yaml kourier.yaml eventing-core.yaml \
           in-memory-channel.yaml mt-channel-broker.yaml; do
    f="$(manifest "$line" "$a")"
    f="$(STEP_LOG=/dev/null derive_apply_set "$line" "$a" "$f")"
    if "$K" apply --server-side --field-manager="$FM" --dry-run=server -f "$f" > "$log.part" 2>&1; then
      printf '  ok        %s/%s\n' "$line" "$a"
    else
      rc=1
      printf '  CONFLICT  %s/%s\n' "$line" "$a"
      # Every error line and the field list under it ("conflict with" for one
      # field, "conflicts with" plus "- <field>" lines for several).
      { grep -E '^(Error|Apply failed|- \.)|conflicts? with' "$log.part" || true; } | sed 's/^/            /'
    fi
    { echo "== $a"; cat "$log.part"; } >> "$log"
  done
  # Post-install files as run_jobs sends them: non-Job objects via apply, each
  # Job via create.
  local other n i
  for a in serving-post-install-jobs.yaml eventing-post-install.yaml; do
    f="$(manifest "$line" "$a")"
    other="$(yq 'select(.kind != "Job" and .kind != null)' "$f")"
    n="$(yq ea -N '[select(.kind == "Job")] | length' "$f")"
    if { [ -z "$other" ] || printf '%s\n' "$other" \
           | "$K" apply --server-side --field-manager="$FM" --dry-run=server -f -; } > "$log.part" 2>&1 \
       && { i=0; while [ "$i" -lt "$n" ]; do
              yq ea -N "[select(.kind == \"Job\")] | .[$i]" "$f" | "$K" create --dry-run=server -f - || exit 1
              i=$((i + 1)); done; } >> "$log.part" 2>&1; then
      printf '  ok        %s/%s (%s non-Job object(s), %s Job(s))\n' "$line" "$a" \
        "$(printf '%s' "$other" | yq ea -N '[select(.kind != null)] | length')" "$n"
    else
      rc=1
      printf '  FAIL      %s/%s\n' "$line" "$a"
      { grep -E '^(Error|Apply failed|- \.)|conflicts? with' "$log.part" || true; } | sed 's/^/            /'
    fi
    { echo "== $a"; cat "$log.part"; } >> "$log"
  done
  rm -f "$log.part"
  return "$rc"
}

# verify: all checks that do not need a new measurement. Exits 1 on any failure.
verify() {
  local fail=0 out="$SPIKE_ROOT/.local/knative-verify.json"
  chk() { if [ "$2" = "$3" ]; then printf '  PASS %-46s %s\n' "$1" "$2"; else printf '  FAIL %-46s got=%s want=%s\n' "$1" "$2" "$3"; fail=1; fi; }

  echo "deployments:"
  local ns d
  for ns in knative-serving kourier-system knative-eventing; do
    while IFS=$'\t' read -r d avail ver; do
      [ -n "$d" ] || continue
      chk "$ns/$d Available (version $ver)" "$avail" "True"
    done < <("$K" -n "$ns" get deploy -o json | jq -r '.items[] | [.metadata.name,
        ((.status.conditions // [])[] | select(.type=="Available") | .status),
        (.metadata.labels["app.kubernetes.io/version"] // "-")] | @tsv')
  done

  echo "webhooks reachable (endpoints ready):"
  for ns_svc in knative-serving/webhook knative-eventing/eventing-webhook; do
    ns="${ns_svc%/*}"; s="${ns_svc#*/}"
    ready="$("$K" -n "$ns" get endpointslices -l "kubernetes.io/service-name=$s" -o json \
      | jq '[.items[].endpoints[]? | select(.conditions.ready == true)] | length')"
    chk "$ns_svc ready endpoints > 0" "$([ "${ready:-0}" -gt 0 ] && echo yes || echo no)" "yes"
  done
  chk "kubectl get ksvc -A works" "$("$K" get ksvc -A >/dev/null 2>&1 && echo yes || echo no)" "yes"

  echo "overrides:"
  chk "config-network ingress-class" \
    "$("$K" -n knative-serving get cm config-network -o jsonpath='{.data.ingress-class}')" \
    "kourier.ingress.networking.knative.dev"
  chk "config-domain has key $KNATIVE_DOMAIN" \
    "$("$K" -n knative-serving get cm config-domain -o json | jq -r --arg d "$KNATIVE_DOMAIN" '.data | has($d)')" "true"
  if [ -f "$SPIKE_ROOT/.local/n2-active" ]; then
    chk "kourier Service type (N2 active)" "$("$K" -n kourier-system get svc kourier -o jsonpath='{.spec.type}')" "ClusterIP"
  fi

  echo "kourier gateway image (CP1 decision a):"
  local ids
  ids="$("$K" -n kourier-system get pods -l app=3scale-kourier-gateway -o json \
    | jq -r '[.items[].status.containerStatuses[]? | select(.name=="kourier-gateway") | .imageID] | unique | join(",")')"
  chk "gateway imageID digest" "${ids##*@}" "$KOURIER_GATEWAY_EXPECTED_DIGEST"

  # Running images with digests and requests/limits per component (B9 Phase 3 step 2).
  for ns in knative-serving kourier-system knative-eventing; do
    "$K" -n "$ns" get pods -o json
  done | jq -s '[.[].items[] | {namespace: .metadata.namespace, pod: .metadata.name,
      containers: [.spec.containers[] as $c | {name: $c.name, image: $c.image, resources: $c.resources,
        imageID: ([.status.containerStatuses[]? | select(.name == $c.name) | .imageID][0])}]}]' > "$out"
  echo "component images and resources: ${out#"$SPIKE_ROOT/"}"

  [ "$fail" -eq 0 ] || ok211::die "knative-verify: at least one check failed (STOP-6 if an override was lost)" 1
  ok211::ok "knative-verify: all checks passed"
}

case "${1:-}" in
  install) line_ok "${2:-}"; install_line "$2" ;;
  verify) verify ;;
  post-install) line_ok "${2:-}"; post_install "$2" ;;
  upgrade) line_ok "${2:-}"; upgrade_line "$2" ;;
  dry-run) line_ok "${2:-}"; dry_run "$2" ;;
  *) ok211::die "usage: $0 install <1.23|1.24>|verify|upgrade <line>|dry-run <line>|post-install <line>" 2 ;;
esac
