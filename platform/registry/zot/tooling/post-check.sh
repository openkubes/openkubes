#!/usr/bin/env bash
set -Eeuo pipefail
case $- in *x*) set +x ;; esac

: "${KUBECTL:=kubectl}"
: "${KUBECONFIG:?KUBECONFIG is required}"
: "${NAMESPACE:=zot}"
: "${RELEASE:=zot}"
: "${REGISTRY_HOST:=registry.ok-shared.internal}"
: "${REGISTRY_LB:=192.168.100.207}"
: "${TLS_SECRET:=zot-server-tls}"
: "${HTPASSWD_SECRET:=zot-htpasswd}"
: "${MACHINE_SECRET:=zot-machine-identities}"
: "${VALUES_FILE:=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/values-ok-shared.yaml}"

d=$(mktemp -d)
test -d "$d"
trap 'rm -rf -- "$d"' EXIT INT TERM

"$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$TLS_SECRET" -n "$NAMESPACE" -o jsonpath='{.data.ca\.crt}' | base64 -d > "$d/ca.crt"
test -s "$d/ca.crt" || { echo "ERROR: TLS CA bundle is empty" >&2; exit 1; }

pod_json=$("$KUBECTL" --kubeconfig "$KUBECONFIG" get pod -n "$NAMESPACE" -l "app.kubernetes.io/instance=$RELEASE,app.kubernetes.io/name=zot" -o json)
printf '%s' "$pod_json" | jq -e '(.items|length)==1 and any(.items[0].status.conditions[]; .type=="Ready" and .status=="True")' >/dev/null
pod_name=$(printf '%s' "$pod_json" | jq -r '.items[0].metadata.name')
echo "POD_READY: $pod_name Ready=True"

cert_status=$("$KUBECTL" --kubeconfig "$KUBECONFIG" get certificate "$TLS_SECRET" -n "$NAMESPACE" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')
[ "$cert_status" = True ] || { echo "ERROR: Certificate Ready=${cert_status:-<none>}" >&2; exit 1; }
echo "CERTIFICATE_READY: $TLS_SECRET Ready=True"

machine_user=$("$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$MACHINE_SECRET" -n "$NAMESPACE" -o jsonpath='{.data.machine-username}' | base64 -d)
machine_password=$("$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$MACHINE_SECRET" -n "$NAMESPACE" -o jsonpath='{.data.machine-password}' | base64 -d)
status=$(curl -sS --resolve "$REGISTRY_HOST:443:$REGISTRY_LB" --cacert "$d/ca.crt" \
  --config <(printf 'user = "%s:%s"\n' "$machine_user" "$machine_password") \
  -D "$d/v2.headers" -o /dev/null -w '%{http_code}' "https://$REGISTRY_HOST/v2/")
[ "$status" = 200 ] || { echo "ERROR: authenticated GET /v2/ returned HTTP $status" >&2; exit 1; }
distribution=$(awk 'BEGIN{IGNORECASE=1} /^docker-distribution-api-version:/ {sub(/\r$/,""); sub(/^[^:]+:[[:space:]]*/,""); print; exit}' "$d/v2.headers")
[ "$distribution" = registry/2.0 ] || { echo "ERROR: /v2/ did not advertise OCI Distribution API registry/2.0" >&2; exit 1; }
release_tag=$("$KUBECTL" --kubeconfig "$KUBECONFIG" logs "$pod_name" -n "$NAMESPACE" | jq -r 'select(.message=="configuration settings") | .params.ReleaseTag' | head -n1)
[ "$release_tag" = v2.1.20 ] || { echo "ERROR: live zot ReleaseTag=${release_tag:-<none>}, expected v2.1.20" >&2; exit 1; }
image_id=$(printf '%s' "$pod_json" | jq -er '.items[0].status.containerStatuses[]|select(.name=="zot")|.imageID')
# Derived from the values file, never a second copy of the digest: a hardcoded expectation
# here would fail against the OLD digest after a version bump and point the operator at the
# wrong thing.
expected_digest=$(VALUES_FILE="$VALUES_FILE" python3 -c 'import os,yaml; print(yaml.safe_load(open(os.environ["VALUES_FILE"],encoding="utf-8"))["image"]["tag"].split("@",1)[1])')
[ -n "$expected_digest" ] || { echo "ERROR: could not read the pinned image digest from $VALUES_FILE" >&2; exit 1; }
[[ "$image_id" == *"$expected_digest" ]] || { echo "ERROR: live imageID $image_id does not match the pinned digest $expected_digest from $VALUES_FILE" >&2; exit 1; }
echo "TLS_ROUTE: GET /v2/ HTTP 200 distribution=$distribution running=$release_tag imageID=$image_id via $REGISTRY_HOST:443:$REGISTRY_LB"

unauth=$(curl -sS --resolve "$REGISTRY_HOST:443:$REGISTRY_LB" --cacert "$d/ca.crt" -o /dev/null -w '%{http_code}' "https://$REGISTRY_HOST/metrics")
case "$unauth" in 401|403) ;; *) echo "ERROR: unauthenticated /metrics returned HTTP $unauth" >&2; exit 1;; esac
metrics_user=$("$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$MACHINE_SECRET" -n "$NAMESPACE" -o jsonpath='{.data.metrics-username}' | base64 -d)
metrics_password=$("$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$MACHINE_SECRET" -n "$NAMESPACE" -o jsonpath='{.data.metrics-password}' | base64 -d)
auth=$(curl -sS --resolve "$REGISTRY_HOST:443:$REGISTRY_LB" --cacert "$d/ca.crt" \
  --config <(printf 'user = "%s:%s"\n' "$metrics_user" "$metrics_password") \
  -o "$d/metrics" -w '%{http_code}' "https://$REGISTRY_HOST/metrics")
[ "$auth" = 200 ] || { echo "ERROR: authenticated /metrics returned HTTP $auth" >&2; exit 1; }
rg -q '^(# (HELP|TYPE) |zot_)' "$d/metrics" || { echo "ERROR: authenticated metrics body has no Prometheus/zot samples" >&2; exit 1; }
echo "METRICS_AUTH: unauthenticated=$unauth authenticated=$auth"

sm=$("$KUBECTL" --kubeconfig "$KUBECONFIG" get servicemonitor "$RELEASE" -n "$NAMESPACE" -o json)
svc=$("$KUBECTL" --kubeconfig "$KUBECONFIG" get service "$RELEASE" -n "$NAMESPACE" -o json)
SM_JSON="$sm" SVC_JSON="$svc" python3 -c 'import json,os; sm=json.loads(os.environ["SM_JSON"]); svc=json.loads(os.environ["SVC_JSON"]); sel=sm["spec"]["selector"]["matchLabels"]; labels=svc["metadata"]["labels"]; assert sel, "empty matchLabels: all() would pass vacuously and select every Service"; assert all(labels.get(k)==v for k,v in sel.items()); assert any(p["name"]=="zot" for p in svc["spec"]["ports"])'
unset SM_JSON SVC_JSON
echo "SERVICEMONITOR_SELECTOR: $NAMESPACE/$RELEASE matches Service $NAMESPACE/$RELEASE labels and named port zot"

# Query each kind separately with --ignore-not-found: a combined get errors outright if
# EITHER CRD is absent, and under pipefail that would take down this whole read-only
# check on its last line, after every real assertion had already passed.
prometheus_count=0
for kind in prometheus prometheusagent; do
  n=$("$KUBECTL" --kubeconfig "$KUBECONFIG" get "$kind" -A --ignore-not-found -o json 2>/dev/null | jq '.items|length' 2>/dev/null || echo 0)
  prometheus_count=$((prometheus_count + n))
done
[ "$prometheus_count" = 0 ] || echo "NOTICE: $prometheus_count Prometheus/PrometheusAgent consumers now exist; selection needs separate verification"
echo "SCRAPE_BOUNDARY: Prometheus/PrometheusAgent count=$prometheus_count; this check does not claim a scrape occurred"
unset machine_password metrics_password
echo "RESULT: PASS — live registry readiness, TLS route, metrics authentication and ServiceMonitor selector effects asserted"
