#!/usr/bin/env bash
#
# OK-211 — SSH tunnel 127.0.0.1:6450 -> VM 127.0.0.1:6443 (BRIEF B8).
#
# Usage: scripts/tunnel.sh start|status|stop
#
# The tunnel is an ssh master with the control socket .local/tun.sock. The
# socket path is relative on purpose: macOS limits Unix socket paths to 104
# bytes and ssh -M appends a suffix, so every command runs from the spike root.
# The tunnel is stopped only through that socket, never with pkill; ok-local's
# `tunnel-stop` patterns ("ssh -L 6443", "ssh -L 6444") do not match this
# command, which starts with `ssh -F /dev/null`.
#
# Exit codes: 0 ok, 1 not running (status), 2 usage, 36 port 6450 held by
#   something else, 37 tunnel did not come up, 30-33 from lib.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
ok211::load_versions
ok211::vm_guard || exit $?

cd "$SPIKE_ROOT"
SOCK=.local/tun.sock

ctl() { # ctl check|exit <ip>
  ssh -F /dev/null -S "$SOCK" -O "$1" "ubuntu@$2" 2>/dev/null
}

listener() {
  lsof -nP -iTCP:"$TUNNEL_PORT" -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $1"/"$2}' | sort -u | tr '\n' ' '
}

case "${1:-}" in
  start)
    ip="$(ok211::vm_ip)"
    if [ -S "$SOCK" ] && ctl check "$ip"; then
      ok211::ok "tunnel already running (127.0.0.1:$TUNNEL_PORT -> $ip:6443)"
      exit 0
    fi
    if [ -e "$SOCK" ]; then
      ok211::warn "stale control socket without a master; removing only that file"
      rm -f "$SOCK"
    fi
    held="$(listener)"
    [ -z "$held" ] || ok211::die "port $TUNNEL_PORT is already held by: $held" 36
    key="$(ok211::ssh_key)"
    ssh -F /dev/null -f -N -M -S "$SOCK" \
      -i "$key" -o IdentitiesOnly=yes -o BatchMode=yes \
      -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=.local/known_hosts \
      -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -E .local/ssh-tunnel.log \
      -L "127.0.0.1:$TUNNEL_PORT:127.0.0.1:6443" "ubuntu@$ip" </dev/null >/dev/null 2>&1 \
      || ok211::die "ssh tunnel failed to start; see .local/ssh-tunnel.log" 37
    ctl check "$ip" || ok211::die "tunnel master not answering after start" 37
    ok211::ok "tunnel up: 127.0.0.1:$TUNNEL_PORT -> $ip:6443 (listener: $(listener))"
    ;;
  status)
    ip="$(ok211::vm_ip)"
    if [ -S "$SOCK" ] && ctl check "$ip"; then
      ok211::ok "tunnel running: 127.0.0.1:$TUNNEL_PORT -> $ip:6443 (listener: $(listener))"
    else
      ok211::warn "tunnel not running (port $TUNNEL_PORT: $(listener | sed 's/^$/free/'))"
      exit 1
    fi
    ;;
  stop)
    if [ ! -e "$SOCK" ]; then
      ok211::info "no control socket; tunnel not running"
      exit 0
    fi
    # The IP is looked up each time: it can change after multipass stop/start.
    # The control command itself only talks to the local socket.
    ip="$(ok211::vm_ip 2>/dev/null || printf '127.0.0.1')"
    if ctl exit "$ip"; then ok211::ok "tunnel stopped"; else ok211::warn "no master answered; removing stale socket"; fi
    rm -f "$SOCK"
    ;;
  *) ok211::die "usage: $0 start|status|stop" 2 ;;
esac
