#!/usr/bin/env bash
#
# OK-211 — X4 (read-only part): Knative's control-plane footprint. CRDs,
# ClusterRoles/ClusterRoleBindings, and the admission webhooks with their
# failurePolicy, rules (including operations), namespace/object selectors and
# timeouts. Writes evidence/raw/x4-footprint-<stamp>.json and a summary.
# jq programs live in single-quoted variables: bash 3.2 brace-expands
# {a, b} inside double quotes in nested command substitutions.
# The caller (make) runs the guard with --node first.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
ok211::load_versions
K="${KUBECTL:-$SPIKE_ROOT/.local/bin/kubectl}"
RAW="$SPIKE_ROOT/evidence/raw"
out="$RAW/x4-footprint-$(ok211::stamp).json"
tmp="$SPIKE_ROOT/.local/tmp/footprint-$(ok211::stamp)"; mkdir -p "$tmp"
PAT='knative|kourier'

# shellcheck disable=SC2016  # jq programs
JQ_CRD='[.items[] | select(.spec.group | test("knative.dev")) | {name: .metadata.name, group: .spec.group, scope: .spec.scope}]'
# shellcheck disable=SC2016
JQ_CR='[.items[] | select((.metadata.name | test($p)) or ((.metadata.labels // {}) | tostring | test($p)))
  | {name: .metadata.name, aggregated: (.aggregationRule != null),
     wildcard: ([.rules[]? | select(((.verbs // []) | index("*")) or ((.resources // []) | index("*")))] | length > 0),
     secrets: ([.rules[]? | select((.resources // []) | index("secrets"))] | length > 0)}]'
# shellcheck disable=SC2016
JQ_CRB='[.items[] | select(.metadata.name | test($p)) | {name: .metadata.name, role: .roleRef.name,
  subjects: [.subjects[]? | "\(.kind)/\(.namespace // "-")/\(.name)"]}]'
# shellcheck disable=SC2016
JQ_WH='[.[].items[] | select(.metadata.name | test($p)) | .kind as $k | .metadata.name as $n | .webhooks[]
  | {kind: $k, configuration: $n, webhook: .name, failurePolicy: .failurePolicy, timeoutSeconds: .timeoutSeconds,
     sideEffects: .sideEffects, service: "\(.clientConfig.service.namespace)/\(.clientConfig.service.name)",
     namespaceSelector: .namespaceSelector, objectSelector: .objectSelector,
     rules: [.rules[]? | {groups: .apiGroups, resources: .resources, operations: .operations}]}]'

"$K" get crd -o json | jq -c "$JQ_CRD" > "$tmp/crd.json"
"$K" get clusterroles -o json | jq -c --arg p "$PAT" "$JQ_CR" > "$tmp/cr.json"
"$K" get clusterrolebindings -o json | jq -c --arg p "$PAT" "$JQ_CRB" > "$tmp/crb.json"
for k in mutatingwebhookconfigurations validatingwebhookconfigurations; do "$K" get "$k" -o json; done \
  | jq -s -c --arg p "$PAT" "$JQ_WH" > "$tmp/wh.json"
jq -n --slurpfile crds "$tmp/crd.json" --slurpfile cr "$tmp/cr.json" --slurpfile crb "$tmp/crb.json" --slurpfile wh "$tmp/wh.json" \
  '{crds: $crds[0], clusterroles: $cr[0], clusterrolebindings: $crb[0], webhooks: $wh[0]}' > "$out"
rm -rf "$tmp"

# shellcheck disable=SC2016
JQ_SUM='
  "CRDs (knative.dev groups): \(.crds | length) — " + (.crds | group_by(.group) | map("\(.[0].group)=\(length)") | join(", ")),
  "ClusterRoles: \(.clusterroles | length) (aggregated \([.clusterroles[] | select(.aggregated)] | length), with a * rule \([.clusterroles[] | select(.wildcard)] | length), with secrets \([.clusterroles[] | select(.secrets)] | length))",
  "  with a * rule: " + ([.clusterroles[] | select(.wildcard) | .name] | join(", ")),
  "ClusterRoleBindings: \(.clusterrolebindings | length)",
  (.clusterrolebindings[] | "  \(.name) -> \(.role) for \(.subjects | join(","))"),
  "Webhooks: \(.webhooks | length)",
  (.webhooks[] | "  \(.kind | sub("WebhookConfiguration"; "")) \(.webhook) failurePolicy=\(.failurePolicy) timeout=\(.timeoutSeconds)s svc=\(.service) ops=\([.rules[].operations[]] | unique | join(",")) groups=\([.rules[].groups[]] | unique | join(",")) nsSel=\(.namespaceSelector | tostring) objSel=\(.objectSelector | tostring)")'
jq -r "$JQ_SUM" "$out"
echo "raw: ${out#"$SPIKE_ROOT/"}"
