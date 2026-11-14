#!/usr/bin/env bash
# Emit a repository Secret from protected local input. Only pipe this to kubectl
# through a guarded Make target; never print its output to a terminal or evidence.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
# shellcheck disable=SC1091
. "$SPIKE_ROOT/versions.env"
cd "$SPIKE_ROOT"
kind="${1:-repository}"
repo="${2:-podinfo-manifests}"
case "$kind" in
  repository) name="ok167-zot-${repo//\//-}"; suffix="/$repo" ;;
  repo-creds) name="ok167-zot-prefix"; suffix="" ;;
  *) ok167::die "expected repository or repo-creds" 2 ;;
esac
case "$repo" in *[!a-zA-Z0-9_./-]*|*..*) ok167::die "invalid repository path" 2 ;; esac
# The password is stdin to jq, not a process argument. Do not source the file.
# shellcheck disable=SC2016  # literal jq variables
password_input() {
  if [ "${WRONG_PASSWORD:-0}" = 1 ]; then printf '%s' 'invalid-review-credential';
  else ok167::credential OK167_GITOPS_PULLER_PASSWORD; fi
}
# shellcheck disable=SC2016  # literal jq variables
password_input \
  | "${JQ:-jq}" -Rs --arg name "$name" --arg ns "$ARGOCD_NAMESPACE" \
      --arg kind "$kind" --arg user "$IDENTITY_PULLER" \
      --arg url "oci://$ZOT_SERVICE_HOST:$ZOT_SERVICE_PORT/$REPO_PREFIX$suffix" \
      '{apiVersion:"v1",kind:"Secret",type:"Opaque",
        metadata:{name:$name,namespace:$ns,
          labels:{"argocd.argoproj.io/secret-type":$kind}},
        stringData:{type:"oci",url:$url,username:$user,password:.}}'
