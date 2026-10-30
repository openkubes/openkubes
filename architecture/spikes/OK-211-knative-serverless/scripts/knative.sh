#!/usr/bin/env bash
#
# OK-211 — install, verify and upgrade Knative from the checksum-verified local
# release manifests (BRIEF B8 "Release-Manifeste und eigene Overrides", B9 Phases 3-4).
#
# Usage: scripts/knative.sh install <line>|verify|upgrade <line>|post-install <line>
#   <line>  1.23 | 1.24
#
# Rules this script implements:
# - Release YAMLs only from .local/manifests/<line>/, each checked against its
#   pin in versions.env immediately before it is applied (B4 rule 10).
# - Release YAMLs are applied server-side with field manager knative-release.
#   Conflicts are never overridden with --force-conflicts: the apply fails and
#   the conflict is reported (B8).
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
WAIT=300s

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

apply_release() { # apply_release <line> <asset>
  local f; f="$(manifest "$1" "$2")"
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
  yq -N 'select(.kind != "Job" and .kind != null)' "$f" > "$tmp/other.yaml"
  if [ -s "$tmp/other.yaml" ]; then
    mark "start" "apply non-Job objects of $(basename "$f")"
    "$K" apply --server-side --field-manager="$FM" -f "$tmp/other.yaml" >/dev/null
    mark "end" "apply non-Job objects of $(basename "$f")"
  fi
  n="$(yq -N '[select(.kind == "Job")] | length' "$f" | awk '{s+=$1} END{print s+0}')"
  i=0
  while [ "$i" -lt "$n" ]; do
    yq -N "[select(.kind == \"Job\")] | .[$i]" "$f" > "$tmp/job-$i.yaml"
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
  *) ok211::die "usage: $0 install <1.23|1.24>|verify|post-install <line>" 2 ;;
esac
