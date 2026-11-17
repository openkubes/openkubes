#!/usr/bin/env bash
#
# OK-211 — ad-hoc read access to the spike cluster (BRIEF B4 rule 3).
#
# Usage: scripts/kc.sh <kubectl args...>
#
# Runs the guard (including the node check), then the pinned kubectl from
# .local/bin/ with the spike kubeconfig. Intended for reading; anything that
# changes the cluster goes through a make target. Secret reads are refused
# (B4 rule 6): a Secret's name may be listed, its data never printed.
#
# Exit codes: those of guard.sh, 40 for a refused command, else kubectl's.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"

export KUBECONFIG="$SPIKE_ROOT/.local/kubeconfig"
export KUBECACHEDIR="$SPIKE_ROOT/.local/kube-cache"
KUBECTL="$SPIKE_ROOT/.local/bin/kubectl"
export KUBECTL

[ "$#" -gt 0 ] || ok211::die "usage: $0 <kubectl args...>" 40

verb="$1"
case "$verb" in
  apply|create|delete|patch|replace|edit|scale|label|annotate|set|rollout|drain|cordon|uncordon|taint|run|expose|autoscale|cp|debug|exec|attach|port-forward|proxy)
    ok211::die "kc.sh is read-only; '$verb' must go through a make target" 40 ;;
  config)
    ok211::die "kc.sh does not run 'kubectl config' (B4 rule 2)" 40 ;;
esac

secret_ref=0 output_flag=0
for a in "$@"; do
  case "$a" in
    --kubeconfig|--kubeconfig=*|--context|--context=*|--cluster|--cluster=*|--server|--server=*|-s|--insecure-skip-tls-verify*|--token|--token=*|--as|--as=*)
      ok211::die "flag '$a' is not allowed (B4 rules 2 and 9)" 40 ;;
    secret|secrets|secret/*|secrets/*|*,secret|*,secrets|secret,*|secrets,*|*,secret,*|*,secrets,*)
      secret_ref=1 ;;
    -o|--output|-o*|--output=*) output_flag=1 ;;
  esac
done
if [ "$secret_ref" = "1" ]; then
  case "$verb" in
    describe) ok211::die "'$verb' on Secrets is not allowed (B4 rule 6)" 40 ;;
  esac
  # `kubectl get secret` without -o prints names, types and key counts only.
  [ "$output_flag" = "0" ] || ok211::die "Secrets may only be listed without -o (B4 rule 6)" 40
fi

"$SCRIPT_DIR/guard.sh" --node >/dev/null 2>"$SPIKE_ROOT/.local/kc-guard.err" || {
  rc=$?; cat "$SPIKE_ROOT/.local/kc-guard.err" >&2; exit "$rc"; }
exec "$KUBECTL" "$@"
