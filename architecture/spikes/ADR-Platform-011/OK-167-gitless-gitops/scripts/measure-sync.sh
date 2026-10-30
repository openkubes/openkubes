#!/usr/bin/env bash
#
# OK-167 — measure how long Argo CD takes to notice and apply a new artifact.
#
# Usage:
#   measure-sync.sh --app <name> --digest <sha256:...> [--image <ref>]
#                   [--namespace <ns>] [--t0 <epoch>] [--timeout <seconds>]
#                   [--label <text>]
#
# Timestamps (UTC epoch seconds), per BRIEF B11:
#   t0  the push finished — passed in with --t0, or taken as "now" at start
#   t1  status.sync.revision equals the new digest          (detection)
#   t2  the sync operation reports Succeeded for it         (apply)
#   t3  status.health.status is Healthy                     (health)
#   t4  every pod of the deployment runs the expected image (rollout)
#
# One JSON line is appended to evidence/raw/measurements.json per run, carrying
# the reconciliation settings that were active — a latency figure without them
# says nothing.
#
# A measurement that does not complete within --timeout is recorded as TIMEOUT
# rather than silently dropped: "it did not happen in 10 minutes" is a result.
#
# Portability: bash 3.2.
#
# Exit codes
#   0  completed
#   1  timed out; the incomplete measurement is retained
#   2  bad arguments

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck source=./lib.sh
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib.sh"
# shellcheck disable=SC1091
. "$SPIKE_ROOT/versions.env"

cd "$SPIKE_ROOT"

KUBECTL="${KUBECTL:-kubectl}"
JQ="${JQ:-jq}"

APP=""
DIGEST=""
IMAGE=""
NAMESPACE=""
T0=""
TIMEOUT=600
LABEL=""

while [ $# -gt 0 ]; do
  case "$1" in
    --app)       APP="${2:-}"; shift 2 ;;
    --digest)    DIGEST="${2:-}"; shift 2 ;;
    --image)     IMAGE="${2:-}"; shift 2 ;;
    --namespace) NAMESPACE="${2:-}"; shift 2 ;;
    --t0)        T0="${2:-}"; shift 2 ;;
    --timeout)   TIMEOUT="${2:-}"; shift 2 ;;
    --label)     LABEL="${2:-}"; shift 2 ;;
    *) ok167::die "unknown argument: $1" 2 ;;
  esac
done

[ -n "$APP" ]    || ok167::die "--app is required" 2
[ -n "$DIGEST" ] || ok167::die "--digest is required" 2

ARGOCD_NS="${ARGOCD_NAMESPACE:-argocd}"
T0="${T0:-$(ok167::epoch)}"

# The settings this measurement ran under. Recorded with every row.
RECONCILE="$("$KUBECTL" -n "$ARGOCD_NS" get cm argocd-cm -o json 2>/dev/null \
  | "$JQ" -r '.data["timeout.reconciliation"] // "unset"')"
JITTER="$("$KUBECTL" -n "$ARGOCD_NS" get cm argocd-cm -o json 2>/dev/null \
  | "$JQ" -r '.data["timeout.reconciliation.jitter"] // "unset"')"

if [ -z "$NAMESPACE" ]; then
  NAMESPACE="$("$KUBECTL" -n "$ARGOCD_NS" get application "$APP" \
    -o jsonpath='{.spec.destination.namespace}' 2>/dev/null || true)"
fi

ok167::info "measuring $APP -> $DIGEST (reconcile=$RECONCILE jitter=$JITTER timeout=${TIMEOUT}s)"

T1=""; T2=""; T3=""; T4=""
LAST_MISS=""; FIRST_MATCH_REQUEST=""; MAX_POLL_MS=0
DEADLINE=$(( T0 + TIMEOUT ))

while [ "$(ok167::epoch)" -lt "$DEADLINE" ]; do
  POLL_START_MS="$("$JQ" -nr 'now * 1000 | floor')"
  APP_JSON="$("$KUBECTL" -n "$ARGOCD_NS" get application "$APP" -o json 2>/dev/null || true)"

  if [ -n "$APP_JSON" ]; then
    revision="$(printf '%s' "$APP_JSON" | "$JQ" -r '.status.sync.revision // ""')"
    sync_status="$(printf '%s' "$APP_JSON" | "$JQ" -r '.status.sync.status // ""')"
    health="$(printf '%s' "$APP_JSON" | "$JQ" -r '.status.health.status // ""')"
    op_phase="$(printf '%s' "$APP_JSON" | "$JQ" -r '.status.operationState.phase // ""')"
    op_revision="$(printf '%s' "$APP_JSON" | "$JQ" -r '.status.operationState.syncResult.revision // ""')"

    if [ "$revision" != "$DIGEST" ]; then LAST_MISS="$POLL_START_MS"; fi
    # t1 — the controller now knows about the new digest
    if [ -z "$T1" ] && [ "$revision" = "$DIGEST" ]; then
      T1="$(ok167::epoch)"
      FIRST_MATCH_REQUEST="$POLL_START_MS"
      ok167::info "t1 detection after $(( T1 - T0 ))s"
    fi

    # t2 — the sync operation for exactly this revision succeeded
    if [ -n "$T1" ] && [ -z "$T2" ] \
       && [ "$op_phase" = "Succeeded" ] && [ "$op_revision" = "$DIGEST" ]; then
      T2="$(ok167::epoch)"
      ok167::info "t2 sync succeeded after $(( T2 - T0 ))s"
    fi

    # t3 — healthy, and synced to the new revision (not merely healthy on the old one)
    if [ -n "$T2" ] && [ -z "$T3" ] \
       && [ "$health" = "Healthy" ] && [ "$sync_status" = "Synced" ] \
       && [ "$revision" = "$DIGEST" ]; then
      T3="$(ok167::epoch)"
      ok167::info "t3 healthy after $(( T3 - T0 ))s"
    fi
  fi

  # t4 — the rollout really finished: every running pod carries the expected image.
  # Checked against the pods, not the Deployment spec: the spec updates the
  # moment Argo CD applies it, while the pods take longer.
  if [ -n "$IMAGE" ] && [ -n "$NAMESPACE" ] && [ -n "$T3" ] && [ -z "$T4" ]; then
    pods_json="$("$KUBECTL" -n "$NAMESPACE" get pods -l app.kubernetes.io/name=podinfo \
      -o json 2>/dev/null || true)"
    if [ -n "$pods_json" ]; then
      total="$(printf '%s' "$pods_json" | "$JQ" -r '[.items[]] | length')"
      # shellcheck disable=SC2016  # a jq program; $img is a jq variable
      matching="$(printf '%s' "$pods_json" | "$JQ" -r --arg img "$IMAGE" \
        '[.items[] | select(.status.phase=="Running")
          | select(all(.spec.containers[]; .image==$img))] | length')"
      desired="$("$KUBECTL" -n "$NAMESPACE" get deployment podinfo \
        -o jsonpath='{.spec.replicas}' 2>/dev/null || echo 0)"
      if [ "${total:-0}" -gt 0 ] && [ "$matching" = "$total" ] && [ "$matching" = "${desired:-0}" ]; then
        T4="$(ok167::epoch)"
        ok167::info "t4 rollout complete after $(( T4 - T0 ))s"
      fi
    fi
  fi

  POLL_END_MS="$("$JQ" -nr 'now * 1000 | floor')"
  POLL_MS=$(( POLL_END_MS - POLL_START_MS ))
  [ "$POLL_MS" -le "$MAX_POLL_MS" ] || MAX_POLL_MS="$POLL_MS"

  # Done when everything that was asked for has been observed.
  if [ -n "$T3" ]; then
    if [ -z "$IMAGE" ] || [ -n "$T4" ]; then break; fi
  fi

  sleep 1
done

elapsed_or_null() {
  if [ -n "$1" ]; then printf '%s' "$(( $1 - T0 ))"; else printf 'null'; fi
}

RESULT="complete"
[ -n "$T3" ] || RESULT="TIMEOUT"
if [ -n "$IMAGE" ] && [ -z "$T4" ] && [ "$RESULT" = "complete" ]; then RESULT="TIMEOUT"; fi

mkdir -p evidence/raw
# shellcheck disable=SC2016  # the $names below are jq variables, not shell ones
"$JQ" -nc \
  --arg app "$APP" --arg digest "$DIGEST" --arg image "${IMAGE:-}" \
  --arg label "$LABEL" --arg result "$RESULT" \
  --arg reconcile "$RECONCILE" --arg jitter "$JITTER" \
  --arg at "$(ok167::timestamp)" \
  --argjson t0 "$T0" \
  --arg t1 "$T1" --arg t2 "$T2" --arg t3 "$T3" --arg t4 "$T4" \
  --arg last_miss "$LAST_MISS" --arg first_match_request "$FIRST_MATCH_REQUEST" \
  --argjson max_poll_ms "$MAX_POLL_MS" \
  --argjson detection "$(elapsed_or_null "$T1")" \
  --argjson sync "$(elapsed_or_null "$T2")" \
  --argjson healthy "$(elapsed_or_null "$T3")" \
  --argjson rollout "$(elapsed_or_null "$T4")" \
  '{at:$at, app:$app, label:$label, digest:$digest, image:$image, result:$result,
    timestamps:{t0:$t0,t1:($t1|if .=="" then null else tonumber end),t2:($t2|if .=="" then null else tonumber end),
      t3:($t3|if .=="" then null else tonumber end),t4:($t4|if .=="" then null else tonumber end)},
    sampling:{interval_seconds:1,max_poll_work_ms:$max_poll_ms,
      last_miss_request_ms:($last_miss|if .=="" then null else tonumber end),
      first_match_request_ms:($first_match_request|if .=="" then null else tonumber end)},
    settings:{reconciliation:$reconcile, jitter:$jitter},
    seconds:{detection:$detection, sync:$sync, healthy:$healthy, rollout:$rollout}}' \
  >> evidence/raw/measurements.json

if [ "$RESULT" = "TIMEOUT" ]; then
  ok167::warn "TIMEOUT after ${TIMEOUT}s — recorded (detection=$(elapsed_or_null "$T1") healthy=$(elapsed_or_null "$T3"))"
  exit 1
else
  ok167::ok "detection=$(elapsed_or_null "$T1")s sync=$(elapsed_or_null "$T2")s healthy=$(elapsed_or_null "$T3")s rollout=$(elapsed_or_null "$T4")s"
fi
