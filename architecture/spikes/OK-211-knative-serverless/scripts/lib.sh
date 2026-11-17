#!/usr/bin/env bash
# OK-211 — shared shell helpers (adapted from OK-167 scripts/lib.sh).
#
# Sourced, never executed. Provides logging with UTC timestamps, small
# utilities, and the only sanctioned way to reach the spike VM:
# ok211::vm_guard, ok211::vm_ip, ok211::vm_ssh, ok211::vm_scp (BRIEF B4 rules 4-5).
#
# Nothing in here talks to a Kubernetes API: scripts/guard.sh is the only place
# that decides whether a cluster may be touched at all.
#
# Portability: bash 3.2 (macOS) — no associative arrays, no mapfile.

# Guard against double-sourcing.
if [ -n "${OK211_LIB_SOURCED:-}" ]; then
  return 0
fi
OK211_LIB_SOURCED=1

OK211_SPIKE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# The one VM this spike may touch. Not configurable on purpose: a different
# value is refused by ok211::vm_guard, it is not an alternative target.
OK211_VM_NAME_EXPECTED="ok-knative-local"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# All timestamps are UTC so evidence from different runs can be ordered without
# worrying about the host's timezone or DST.

ok211::timestamp() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

# Compact form for file names.
ok211::stamp() {
  date -u +%Y%m%dT%H%M%SZ
}

ok211::epoch() {
  date -u +%s
}

# Colours only when stderr is a terminal, so redirected output stays clean.
if [ -t 2 ]; then
  OK211_C_RED=$'\033[31m'
  OK211_C_YELLOW=$'\033[33m'
  OK211_C_GREEN=$'\033[32m'
  OK211_C_DIM=$'\033[2m'
  OK211_C_RESET=$'\033[0m'
else
  OK211_C_RED=''
  OK211_C_YELLOW=''
  OK211_C_GREEN=''
  OK211_C_DIM=''
  OK211_C_RESET=''
fi

ok211::info() {
  printf '%s%s%s %s\n' "$OK211_C_DIM" "$(ok211::timestamp)" "$OK211_C_RESET" "$*" >&2
}

ok211::ok() {
  printf '%s%s%s %sPASS%s %s\n' \
    "$OK211_C_DIM" "$(ok211::timestamp)" "$OK211_C_RESET" \
    "$OK211_C_GREEN" "$OK211_C_RESET" "$*" >&2
}

ok211::warn() {
  printf '%s%s%s %sWARN%s %s\n' \
    "$OK211_C_DIM" "$(ok211::timestamp)" "$OK211_C_RESET" \
    "$OK211_C_YELLOW" "$OK211_C_RESET" "$*" >&2
}

ok211::error() {
  printf '%s%s%s %sFAIL%s %s\n' \
    "$OK211_C_DIM" "$(ok211::timestamp)" "$OK211_C_RESET" \
    "$OK211_C_RED" "$OK211_C_RESET" "$*" >&2
}

# Exit codes are part of each script's contract; see the header of the caller.
ok211::die() {
  local code="${2:-1}"
  ok211::error "$1"
  exit "$code"
}

# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------

ok211::require_tool() {
  local tool="$1"
  local hint="${2:-}"
  if ! command -v "$tool" >/dev/null 2>&1; then
    if [ -n "$hint" ]; then
      ok211::die "required tool not found: $tool ($hint)" 2
    fi
    ok211::die "required tool not found: $tool" 2
  fi
}

ok211::require_file() {
  local path="$1"
  local what="${2:-file}"
  [ -f "$path" ] || ok211::die "required $what not found: $path" 2
}

# Load versions.env into the environment (the Makefile does the same via
# `include`). Plain KEY=value lines only, so sourcing is safe.
ok211::load_versions() {
  ok211::require_file "$OK211_SPIKE_ROOT/versions.env" "versions.env"
  # shellcheck disable=SC1091
  . "$OK211_SPIKE_ROOT/versions.env"
}

# ---------------------------------------------------------------------------
# Secret hygiene
# ---------------------------------------------------------------------------

# Create a file that only the owner can read, before anything is written into
# it. Used for every file under .local/ that holds credentials (BRIEF B4 rule 6).
ok211::touch_private() {
  local path="$1"
  : > "$path"
  chmod 600 "$path"
}

# Assert a path really is mode 600.
ok211::assert_private() {
  local path="$1"
  [ -f "$path" ] || ok211::die "expected a private file at $path" 2
  local mode
  mode=$(stat -f '%OLp' "$path" 2>/dev/null || stat -c '%a' "$path" 2>/dev/null)
  [ "$mode" = "600" ] || ok211::die "insecure permissions on $path: $mode, expected 600" 2
}

# Rewrite home paths as ~ for evidence (BRIEF B12).
ok211::tilde() {
  sed "s|$HOME|~|g"
}

# ---------------------------------------------------------------------------
# VM access — the only sanctioned path (BRIEF B4 rules 4-5, B8)
# ---------------------------------------------------------------------------

# Refuse anything but the spike VM. Every target that calls multipass, ssh or
# scp runs this first.
ok211::vm_guard() {
  if [ "${VM_NAME:-}" != "$OK211_VM_NAME_EXPECTED" ]; then
    ok211::error "VM_NAME is '${VM_NAME:-<unset>}', only '$OK211_VM_NAME_EXPECTED' may be touched."
    ok211::error "ok-mgmt-local, ok-infra-local and every other instance are out of scope."
    return 30
  fi
}

# The VM's reachable IPv4. After the K3s install `multipass info` also lists
# flannel/CNI addresses; the first address must not be one of those (B8).
ok211::vm_ip() {
  ok211::vm_guard || return $?
  local ip
  ip="$(multipass info "$OK211_VM_NAME_EXPECTED" --format json 2>/dev/null \
    | jq -r --arg n "$OK211_VM_NAME_EXPECTED" '.info[$n].ipv4[0] // empty')"
  if [ -z "$ip" ]; then
    ok211::error "no IPv4 for $OK211_VM_NAME_EXPECTED (is it running? 'make vm-info')"
    return 31
  fi
  if ! printf '%s' "$ip" | grep -qE '^[0-9]{1,3}(\.[0-9]{1,3}){3}$'; then
    ok211::error "unexpected address format from multipass: $ip"
    return 31
  fi
  case "$ip" in
    10.42.*|10.43.*)
      ok211::error "first address $ip is a K3s pod/service CIDR address, not the VM address"
      return 32
      ;;
  esac
  printf '%s\n' "$ip"
}

# The public key cloud-init installs: the same order as ok-local's SSH_KEY.
# Only the .pub file is ever read; the private key is passed to ssh by path.
ok211::ssh_pubkey() {
  if [ -n "${OK211_SSH_PUBKEY:-}" ]; then
    printf '%s\n' "$OK211_SSH_PUBKEY"
  elif [ -f "$HOME/.ssh/id_ed25519.pub" ]; then
    printf '%s\n' "$HOME/.ssh/id_ed25519.pub"
  else
    printf '%s\n' "$HOME/.ssh/id_rsa.pub"
  fi
}

ok211::ssh_key() {
  local pub key
  pub="$(ok211::ssh_pubkey)"
  key="${pub%.pub}"
  [ -f "$pub" ] || { ok211::error "public key not found: $pub"; return 33; }
  # Existence only. The content of the private key is never read here.
  [ -e "$key" ] || { ok211::error "private key for $pub not found"; return 33; }
  printf '%s\n' "$key"
}

# Common ssh options: no user config, only the named key, no prompts, and a
# known_hosts file inside .local/ (never ~/.ssh/known_hosts).
ok211::_ssh_opts() {
  local key="$1"
  printf '%s\n' \
    -F /dev/null \
    -i "$key" \
    -o IdentitiesOnly=yes \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=accept-new \
    -o "UserKnownHostsFile=$OK211_SPIKE_ROOT/.local/known_hosts" \
    -o ConnectTimeout=10
}

# ok211::vm_ssh <remote command...>
ok211::vm_ssh() {
  local ip key opts=() o
  ip="$(ok211::vm_ip)" || return $?
  key="$(ok211::ssh_key)" || return $?
  while IFS= read -r o; do opts+=("$o"); done < <(ok211::_ssh_opts "$key")
  # The remote command is meant to be expanded by the remote shell.
  # shellcheck disable=SC2029
  ssh "${opts[@]}" "ubuntu@$ip" "$@"
}

# ok211::vm_scp <local file> <remote path>
ok211::vm_scp() {
  local src="$1" dst="$2" ip key opts=() o
  ip="$(ok211::vm_ip)" || return $?
  key="$(ok211::ssh_key)" || return $?
  while IFS= read -r o; do opts+=("$o"); done < <(ok211::_ssh_opts "$key")
  scp -q "${opts[@]}" "$src" "ubuntu@$ip:$dst"
}
