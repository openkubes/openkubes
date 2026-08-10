#!/usr/bin/env bash
set -Eeuo pipefail
case $- in *x*) set +x ;; esac

: "${KUBECTL:=kubectl}"
: "${KUBECONFIG:?KUBECONFIG is required}"
: "${NAMESPACE:=zot}"
: "${HTPASSWD_SECRET:=zot-htpasswd}"
: "${MACHINE_SECRET:=zot-machine-identities}"
: "${CONFORMANCE_SECRET:=zot-conformance-identities}"
: "${RELEASE_HINT:=zot}"

# The htpasswd Secret is mounted into the registry container, and the zot chart projects an
# external Secret with no `items:` filter -- every key becomes a readable file inside the
# process. So the bcrypt digests live here ALONE; the cleartext machine passwords live in a
# separate Secret that is never mounted into the registry. Keeping them together made the
# bcrypt hashing pointless, because the cleartext shipped alongside it.
#
# The two are only meaningful as a pair (bcrypt is one-way, so a lone htpasswd cannot be
# reassociated with its passwords). Reconcile them atomically: complete pair -> untouched;
# anything else -> regenerate both, which rotates the machine credentials.
htpasswd_ok=false
machine_ok=false
"$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$HTPASSWD_SECRET" -n "$NAMESPACE" -o json 2>/dev/null |
  jq -e '.data.htpasswd' >/dev/null 2>&1 && htpasswd_ok=true
"$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$MACHINE_SECRET" -n "$NAMESPACE" -o json 2>/dev/null |
  jq -e '.data["machine-username"] and .data["machine-password"] and
    .data["puller-username"] and .data["puller-password"] and
    .data["metrics-username"] and .data["metrics-password"]' >/dev/null 2>&1 && machine_ok=true

if [ "$htpasswd_ok" = true ] && [ "$machine_ok" = true ]; then
  echo "UNCHANGED: Secrets $NAMESPACE/$HTPASSWD_SECRET and $NAMESPACE/$MACHINE_SECRET contain the required identities"
else
  if [ "$htpasswd_ok" = true ] || [ "$machine_ok" = true ]; then
    echo "NOTICE: only one of $HTPASSWD_SECRET/$MACHINE_SECRET was complete; regenerating both rotates the machine credentials" >&2
  fi
  machine_user=zot-machine
  puller_user=zot-puller
  metrics_user=zot-metrics
  machine_password=$(openssl rand -base64 36 | tr -d '\n')
  puller_password=$(openssl rand -base64 36 | tr -d '\n')
  metrics_password=$(openssl rand -base64 36 | tr -d '\n')
  machine_line=$(printf '%s\n' "$machine_password" | htpasswd -niBC 12 "$machine_user")
  puller_line=$(printf '%s\n' "$puller_password" | htpasswd -niBC 12 "$puller_user")
  metrics_line=$(printf '%s\n' "$metrics_password" | htpasswd -niBC 12 "$metrics_user")
  htpasswd_value=$(printf '%s\n%s\n%s\n' "$machine_line" "$puller_line" "$metrics_line")
  {
    printf 'apiVersion: v1\nkind: Secret\nmetadata:\n  name: %s\n  namespace: %s\ntype: Opaque\nstringData:\n' "$HTPASSWD_SECRET" "$NAMESPACE"
    printf '  htpasswd: |\n'
    printf '%s\n' "$htpasswd_value" | sed 's/^/    /'
    printf -- '---\n'
    printf 'apiVersion: v1\nkind: Secret\nmetadata:\n  name: %s\n  namespace: %s\ntype: Opaque\nstringData:\n' "$MACHINE_SECRET" "$NAMESPACE"
    printf '  machine-username: %s\n' "$machine_user"
    printf '  machine-password: %s\n' "$machine_password"
    printf '  puller-username: %s\n' "$puller_user"
    printf '  puller-password: %s\n' "$puller_password"
    printf '  metrics-username: %s\n' "$metrics_user"
    printf '  metrics-password: %s\n' "$metrics_password"
  } | "$KUBECTL" --kubeconfig "$KUBECONFIG" apply -f - >/dev/null
  unset machine_password puller_password metrics_password machine_line puller_line metrics_line htpasswd_value
  echo "CREATED: Secrets $NAMESPACE/$HTPASSWD_SECRET (digests) and $NAMESPACE/$MACHINE_SECRET (cleartext, never mounted into the registry)"
  echo "NOTICE: zot parses htpasswd at startup, so rotated machine credentials do not take effect"
  echo "        until the registry restarts. Until then every authenticated call returns 401."
  echo "        Roll it with: kubectl rollout restart statefulset/$RELEASE_HINT -n $NAMESPACE"
fi

if "$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$CONFORMANCE_SECRET" -n "$NAMESPACE" >/dev/null 2>&1; then
  "$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$CONFORMANCE_SECRET" -n "$NAMESPACE" -o json |
    jq -e '.data["writer-username"] and .data["writer-password"] and
      .data["reader-username"] and .data["reader-password"]' >/dev/null
  echo "UNCHANGED: Secret $NAMESPACE/$CONFORMANCE_SECRET contains the required identities"
else
  writer_user=zot-writer
  reader_user=zot-reader
  writer_password=$(openssl rand -base64 36 | tr -d '\n')
  reader_password=$(openssl rand -base64 36 | tr -d '\n')
  {
    printf 'apiVersion: v1\nkind: Secret\nmetadata:\n  name: %s\n  namespace: %s\ntype: Opaque\nstringData:\n' "$CONFORMANCE_SECRET" "$NAMESPACE"
    printf '  writer-username: %s\n' "$writer_user"
    printf '  writer-password: %s\n' "$writer_password"
    printf '  reader-username: %s\n' "$reader_user"
    printf '  reader-password: %s\n' "$reader_password"
  } | "$KUBECTL" --kubeconfig "$KUBECONFIG" apply -f - >/dev/null
  unset writer_password reader_password
  echo "CREATED: Secret $NAMESPACE/$CONFORMANCE_SECRET (values not printed)"
fi
