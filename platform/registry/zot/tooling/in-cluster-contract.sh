#!/usr/bin/env bash
set -Eeuo pipefail

: "${KUBECTL:=kubectl}"
: "${KUBECONFIG:?KUBECONFIG is required}"
: "${NAMESPACE:=zot}"
: "${REGISTRY_HOST:=registry.ok-shared.internal}"
: "${REGISTRY_LB:=192.168.100.207}"
: "${TLS_SECRET:=zot-server-tls}"
: "${MACHINE_SECRET:=zot-machine-identities}"

run_id=${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$$}
safe_id=$(printf '%s' "$run_id" | tr '[:upper:]_' '[:lower:]-' | tr -cd 'a-z0-9-' | cut -c1-38)
job_name="zot-contract-$safe_id"
[ -n "$safe_id" ] || { echo "ERROR: RUN_ID has no Kubernetes-safe characters" >&2; exit 2; }

existing=$("$KUBECTL" --kubeconfig "$KUBECONFIG" get job "$job_name" -n "$NAMESPACE" --ignore-not-found -o name)
[ -z "$existing" ] || { echo "ERROR: repeatable run id guard: $existing already exists; choose a new RUN_ID" >&2; exit 2; }

d=$(mktemp -d)
test -d "$d"
trap 'rm -rf -- "$d"' EXIT INT TERM
"$KUBECTL" --kubeconfig "$KUBECONFIG" create configmap zot-contract-script -n "$NAMESPACE" \
  --from-file=in-cluster-contract.py="$(dirname "$0")/in-cluster-contract.py" --dry-run=client -o yaml |
  "$KUBECTL" --kubeconfig "$KUBECONFIG" apply -f - >/dev/null
NAMESPACE="$NAMESPACE" JOB_NAME="$job_name" REGISTRY_HOST="$REGISTRY_HOST" REGISTRY_LB="$REGISTRY_LB" RUN_ID="$safe_id" TLS_SECRET="$TLS_SECRET" MACHINE_SECRET="$MACHINE_SECRET" \
  python3 -c 'import os,string,sys; print(string.Template(open(sys.argv[1]).read()).substitute(os.environ),end="")' \
  "$(dirname "$0")/../manifests/contract-job.template.yaml" > "$d/job.yaml"
"$KUBECTL" --kubeconfig "$KUBECONFIG" apply -f "$d/job.yaml" >/dev/null
if ! "$KUBECTL" --kubeconfig "$KUBECONFIG" wait --for=condition=Complete job/"$job_name" -n "$NAMESPACE" --timeout=5m; then
  "$KUBECTL" --kubeconfig "$KUBECONFIG" describe job "$job_name" -n "$NAMESPACE" >&2
  "$KUBECTL" --kubeconfig "$KUBECONFIG" logs job/"$job_name" -n "$NAMESPACE" >&2 || true
  exit 1
fi
logs=$("$KUBECTL" --kubeconfig "$KUBECONFIG" logs job/"$job_name" -n "$NAMESPACE")
printf '%s\n' "$logs"
printf '%s\n' "$logs" | rg -q '^RESULT: PASS$' || { echo "ERROR: contract Job did not report PASS" >&2; exit 1; }
printf '%s\n' "$logs" | rg -q '^BOUNDARY: in-cluster OCI contract proven; kubelet image pull NOT proven$' || { echo "ERROR: proof boundary missing" >&2; exit 1; }
