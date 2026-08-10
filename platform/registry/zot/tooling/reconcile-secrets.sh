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
# Fail closed on anything that is not a clean "absent". Swallowing every error into "absent"
# would let a transient apiserver blip take the regenerate branch and rotate credentials the
# running registry is still serving, which is a far worse outcome than stopping.
secret_json() {
  local name="$1" out rc
  out=$("$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$name" -n "$NAMESPACE" -o json 2>"$err_file"); rc=$?
  if [ "$rc" -eq 0 ]; then printf '%s' "$out"; return 0; fi
  if grep -qF 'NotFound' "$err_file" || grep -qF 'not found' "$err_file"; then return 1; fi
  echo "ERROR: reading Secret $NAMESPACE/$name failed for a reason other than absence:" >&2
  cat "$err_file" >&2
  exit 1
}

err_file=$(mktemp)
trap 'rm -f -- "$err_file"' EXIT INT TERM

htpasswd_ok=false
machine_ok=false
if json=$(secret_json "$HTPASSWD_SECRET"); then
  printf '%s' "$json" | jq -e '.data.htpasswd' >/dev/null 2>&1 && htpasswd_ok=true
fi
if json=$(secret_json "$MACHINE_SECRET"); then
  printf '%s' "$json" | jq -e '.data["machine-username"] and .data["machine-password"] and
    .data["puller-username"] and .data["puller-password"] and
    .data["metrics-username"] and .data["metrics-password"]' >/dev/null 2>&1 && machine_ok=true
fi

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
