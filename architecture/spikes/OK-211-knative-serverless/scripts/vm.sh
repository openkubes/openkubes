#!/usr/bin/env bash
#
# OK-211 — lifecycle of the spike VM ok-knative-local (BRIEF B8, B9 Phase 2).
#
# Usage: scripts/vm.sh up|info|stop|start|snapshot <name>|restore <name>|delete
#
# Every multipass call names the instance explicitly (B4 rule 4). There is no
# code path that runs multipass without the instance name, with --all, purge
# or set. `delete` is reached only through `make vm-delete CONFIRM=yes`.
#
# Exit codes: 0 ok, 2 usage/prerequisite, 30-33 vm_guard/vm_ip/ssh key, 34 timeout,
#   35 the instance is in a state that does not allow the action.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
ok211::load_versions
ok211::vm_guard || exit $?
ok211::require_tool multipass
ok211::require_tool jq

action="${1:-}"
LOCAL="$SPIKE_ROOT/.local"

state() {
  multipass info "$VM_NAME" --format json 2>/dev/null \
    | jq -r --arg n "$VM_NAME" '.info[$n].state // "Absent"' || printf 'Absent\n'
}

wait_ssh() {
  for _ in $(seq 1 60); do
    if ok211::vm_ssh true 2>/dev/null; then return 0; fi
    sleep 5
  done
  ok211::die "SSH to $VM_NAME did not answer within 300 s" 34
}

render_cloud_init() {
  local pub line
  pub="$(ok211::ssh_pubkey)"
  [ -f "$pub" ] || ok211::die "public key not found: $pub" 33
  line="$(head -1 "$pub")"
  printf '%s' "$line" | grep -qE '^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)) [A-Za-z0-9+/=]+( .*)?$' \
    || ok211::die "$(printf '%s' "$pub" | ok211::tilde) does not look like a single OpenSSH public key" 33
  mkdir -p "$LOCAL"
  ok211::touch_private "$LOCAL/cloud-init.yaml"
  # awk instead of sed: the key contains '/' and '+'.
  awk -v key="$line" '{ gsub(/__SSH_PUBLIC_KEY__/, key); print }' \
    "$SPIKE_ROOT/vm/cloud-init.template.yaml" > "$LOCAL/cloud-init.yaml"
  grep -q '__SSH_PUBLIC_KEY__' "$LOCAL/cloud-init.yaml" && ok211::die "placeholder not replaced" 2
  ok211::info "cloud-init rendered to .local/cloud-init.yaml with $(ssh-keygen -lf "$pub" | awk '{print $2}')"
}

case "$action" in
  up)
    s="$(state)"
    if [ "$s" = "Absent" ]; then
      render_cloud_init
      ok211::info "multipass launch $VM_IMAGE --name $VM_NAME --cpus $VM_CPUS --memory $VM_MEMORY --disk $VM_DISK"
      multipass launch "$VM_IMAGE" --name "$VM_NAME" --cpus "$VM_CPUS" --memory "$VM_MEMORY" \
        --disk "$VM_DISK" --cloud-init "$LOCAL/cloud-init.yaml" --timeout 900
    elif [ "$s" = "Stopped" ]; then
      ok211::info "$VM_NAME exists and is stopped; starting it"
      multipass start "$VM_NAME"
    else
      ok211::info "$VM_NAME already exists (state: $s); not launching again"
    fi
    wait_ssh
    ok211::vm_ssh 'cloud-init status --wait >/dev/null; cloud-init status' | sed 's/^/  cloud-init: /' >&2
    ok211::ok "$VM_NAME is up at $(ok211::vm_ip), SSH answers"
    ;;
  info)
    multipass info "$VM_NAME"
    ;;
  stop)
    [ "$(state)" = "Absent" ] && ok211::die "$VM_NAME does not exist" 35
    multipass stop "$VM_NAME"
    ok211::ok "$VM_NAME stopped"
    ;;
  start)
    [ "$(state)" = "Absent" ] && ok211::die "$VM_NAME does not exist" 35
    multipass start "$VM_NAME"
    wait_ssh
    ok211::ok "$VM_NAME started at $(ok211::vm_ip)"
    ;;
  snapshot)
    name="${2:-}"; [ -n "$name" ] || ok211::die "usage: $0 snapshot <name>" 2
    [ "$(state)" = "Stopped" ] || ok211::die "multipass snapshots need a stopped instance; run 'make down' first" 35
    multipass snapshot "$VM_NAME" --name "$name"
    ok211::ok "snapshot $VM_NAME.$name taken"
    ;;
  restore)
    name="${2:-}"; [ -n "$name" ] || ok211::die "usage: $0 restore <name>" 2
    [ "$(state)" = "Stopped" ] || ok211::die "restore needs a stopped instance; run 'make down' first" 35
    multipass restore "$VM_NAME.$name" --destructive
    ok211::ok "$VM_NAME restored to snapshot $name"
    ;;
  delete)
    [ "${CONFIRM:-}" = "yes" ] || ok211::die "refusing to delete without CONFIRM=yes" 2
    "$SCRIPT_DIR/tunnel.sh" stop || true
    if [ "$(state)" != "Absent" ]; then
      multipass delete --purge "$VM_NAME"
    fi
    rm -f "$LOCAL/known_hosts" "$LOCAL/kubeconfig" "$LOCAL/tun.sock"
    ok211::ok "$VM_NAME deleted; known_hosts, kubeconfig and tunnel socket removed"
    ;;
  *)
    ok211::die "usage: $0 up|info|stop|start|snapshot <name>|restore <name>|delete" 2
    ;;
esac
