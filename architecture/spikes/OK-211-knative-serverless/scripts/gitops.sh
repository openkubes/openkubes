#!/usr/bin/env bash
#
# OK-211 — G1/G2: declarative re-apply and drift (BRIEF B9 Phase 9).
#
# Usage: scripts/gitops.sh diff <label> | reapply | g2
#   diff <label>  kubectl diff --server-side for every set with its own field manager:
#                 knative-release (derived release files, as the apply sends them),
#                 cert-manager-release, traefik-chart (rendered chart), ok211 (gitops/current-set.txt).
#                 Writes evidence/raw/g1-diff-<label>-<stamp>.txt; exit codes per file.
#   reapply       second apply of everything: knative.sh install 1.24 (release in order, overrides),
#                 cert-manager manifest, rendered Traefik chart, own set
#   g2            ksvc g2-podinfo: apply, then client-side and server-side diff of the same file;
#                 fields the Knative webhook added (live spec vs manifest)
# The caller (make) runs the guard with --node first.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
ok211::load_versions
K="${KUBECTL:-$SPIKE_ROOT/.local/bin/kubectl}"
RAW="$SPIKE_ROOT/evidence/raw"
cd "$SPIKE_ROOT"

own_set() { grep -vE '^(#|$)' gitops/current-set.txt; }
RELEASE_ASSETS="serving-crds.yaml eventing-crds.yaml serving-core.yaml kourier.yaml eventing-core.yaml in-memory-channel.yaml mt-channel-broker.yaml"

# release_file <asset> -> the file the apply sends (derived if a rule applies)
release_file() {
  local d=".local/manifests/1.24/derived/$1"
  if [ -f "$d" ]; then printf '%s\n' "$d"; else printf '%s\n' ".local/manifests/1.24/$1"; fi
}

# one_diff <field manager> <label> <file or -> : prints "rc lines"
one_diff() {
  local fm="$1" label="$2" src="$3" rc=0 o
  o="$("$K" diff --server-side --field-manager="$fm" -f "$src" 2>&1)" || rc=$?
  printf '### %s (field manager %s): exit %s\n' "$label" "$fm" "$rc"
  if [ "$rc" -ne 0 ]; then printf '%s\n' "$o" | grep -vE '^Warning: Kubernetes default value is insecure' | head -80; fi
}

diff_all() {
  local label="$1" out f
  out="$RAW/g1-diff-$label-$(ok211::stamp).txt"
  {
    echo "# G1 diff '$label' $(ok211::timestamp) — kubectl diff --server-side; exit 0 = no difference, 1 = difference, >1 = error"
    for a in $RELEASE_ASSETS; do one_diff knative-release "1.24/$a" "$(release_file "$a")"; done
    one_diff cert-manager-release cert-manager.yaml .local/manifests/cert-manager/cert-manager.yaml
    [ -f .local/traefik-rendered.yaml ] && one_diff traefik-chart traefik-rendered .local/traefik-rendered.yaml
    while IFS= read -r f; do
      "$SCRIPT_DIR/render.sh" "$f" > ".local/tmp-g1-own.yaml"
      one_diff ok211 "$f" .local/tmp-g1-own.yaml
    done < <(own_set)
    rm -f .local/tmp-g1-own.yaml
  } > "$out"
  grep '^### ' "$out"
  echo "raw: ${out#"$SPIKE_ROOT/"}"
}

reapply() {
  local f
  STEP_LOG="$RAW/g1-reapply-steps.log" "$SCRIPT_DIR/knative.sh" install 1.24
  "$K" apply --server-side --field-manager=cert-manager-release -f .local/manifests/cert-manager/cert-manager.yaml >/dev/null
  [ -f .local/traefik-rendered.yaml ] && "$K" apply --server-side --field-manager=traefik-chart -f .local/traefik-rendered.yaml >/dev/null
  while IFS= read -r f; do
    "$SCRIPT_DIR/render.sh" "$f" | "$K" apply --server-side --field-manager=ok211 -f - 2>&1 >/dev/null | grep -v '^Warning: Kubernetes default' || true
    echo "applied $f"
  done < <(own_set)
}

g2() {
  local out m=apps/serving/g2-podinfo.yaml rc_c=0 rc_s=0 dc ds
  out="$RAW/g2-defaulting-$(ok211::stamp).txt"
  "$SCRIPT_DIR/render.sh" "$m" > .local/tmp-g2.yaml
  "$K" apply --server-side --field-manager=ok211 -f .local/tmp-g2.yaml >/dev/null 2>&1
  "$K" -n ok211-serving wait --for=condition=Ready ksvc/g2-podinfo --timeout=300s >/dev/null
  dc="$("$K" diff -f .local/tmp-g2.yaml 2>&1)" || rc_c=$?
  ds="$("$K" diff --server-side --field-manager=ok211 -f .local/tmp-g2.yaml 2>&1)" || rc_s=$?
  {
    echo "# G2 $(ok211::timestamp) — ksvc g2-podinfo applied server-side (field manager ok211), then diffed"
    echo "## client-side kubectl diff: exit $rc_c"; printf '%s\n' "$dc" | grep -v '^Warning: Kubernetes default' || true
    echo "## server-side kubectl diff --server-side: exit $rc_s"; printf '%s\n' "$ds" | grep -v '^Warning: Kubernetes default' || true
    echo "## manifest .spec"; yq -o=json -I=0 'select(.kind == "Service") | .spec' .local/tmp-g2.yaml
    echo "## live .spec (after the webhook's defaulting)"; "$K" -n ok211-serving get ksvc g2-podinfo -o json | jq -c '.spec'
    echo "## fields in live .spec that the manifest does not set (paths)"
    jq -n --argjson m "$(yq -o=json -I=0 'select(.kind == "Service") | .spec' .local/tmp-g2.yaml)" --argjson l "$("$K" -n ok211-serving get ksvc g2-podinfo -o json | jq -c '.spec')" \
      '[$l | paths(scalars)] - [$m | paths(scalars)] | map(map(tostring) | join(".")) | .[]' -r
    echo "## live annotations added"; "$K" -n ok211-serving get ksvc g2-podinfo -o json | jq -c '.metadata.annotations'
    echo "## managedFields"; "$K" -n ok211-serving get ksvc g2-podinfo -o json --show-managed-fields | jq -c '[.metadata.managedFields[] | {manager, operation, subresource}]'
  } > "$out"
  rm -f .local/tmp-g2.yaml
  cat "$out"
}

case "${1:-}" in
  diff) diff_all "${2:-now}" ;;
  reapply) reapply ;;
  g2) g2 ;;
  *) ok211::die "usage: $0 diff <label>|reapply|g2" 2 ;;
esac
