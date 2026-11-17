#!/usr/bin/env bash
#
# OK-211 — read-only preflight (BRIEF B8 `preflight`, B9 Phase 0).
#
# Records host resources, tools, Multipass state (read only), ports, the
# isolated KUBECONFIG, and whether the local release manifests still match
# their pins. Writes the raw record to evidence/raw/preflight-<stamp>.txt with
# home paths as ~. The curated summary lives in evidence/00-preflight.md and is
# not overwritten.
#
# Changes nothing: no multipass command other than version/get/list/info, no
# download, no cluster access.
#
# Exit codes: 0 no blocking condition; 1 a blocking condition (listed at the end).
#   Low memory (STOP-8) is reported as WARN, because the human may accept it
#   at CP1 (as on 2026-10-30); it never blocks silently either.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
ok211::load_versions

mkdir -p "$SPIKE_ROOT/evidence/raw"
out="$SPIKE_ROOT/evidence/raw/preflight-$(ok211::stamp).txt"
blocking=""

section() { printf '\n== %s\n' "$1"; }

{
  printf '# OK-211 preflight raw record\n'
  printf 'date_utc: %s\n' "$(ok211::timestamp)"
  printf 'commit: %s\n' "$(git -C "$SPIKE_ROOT" rev-parse HEAD 2>/dev/null)"

  section "host"
  printf 'arch: %s\n' "$(uname -m)"
  sw_vers | sed 's/^/  /'
  printf 'cpus: %s\nmemsize_bytes: %s\nloadavg: %s\n' "$(sysctl -n hw.ncpu)" "$(sysctl -n hw.memsize)" "$(sysctl -n vm.loadavg)"
  avail="$(vm_stat | awk -F: '/page size of/{match($0,/[0-9]+ bytes/); ps=substr($0,RSTART,RLENGTH)+0}
    /Pages free|Pages inactive|Pages speculative|Pages purgeable/{gsub(/[ .]/,"",$2); s+=$2}
    END{printf "%d %d %.2f", s, ps, s*ps/1073741824}')"
  read -r avail_pages page_size avail_gib <<< "$avail"
  printf 'available_pages: %s  page_size: %s  available_gib: %s  (STOP-8 formula)\n' "$avail_pages" "$page_size" "$avail_gib"
  printf 'memory_pressure: %s\n' "$(memory_pressure -Q | tail -1)"
  df -h "$HOME" | tail -1 | awk '{print "disk_free: " $4 " of " $2}'
  if pgrep -x com.docker.backend >/dev/null 2>&1; then echo "docker_desktop: running"; else echo "docker_desktop: not running"; fi
  awk -v a="$avail_gib" 'BEGIN{exit !(a < 10)}' && printf 'WARN STOP-8: available memory %s GiB < 10 GiB (human decision at CP1 required or recorded)\n' "$avail_gib"

  section "multipass (read only)"
  if command -v multipass >/dev/null 2>&1; then
    multipass version 2>&1 | grep -E '^multipass' | sed 's/^/  /'
    printf 'local.driver: %s\n' "$(multipass get local.driver 2>&1)"
    echo "multipass list:"; multipass list 2>&1 | sed 's/^/  /'
  else
    echo "multipass: NOT INSTALLED"; echo "BLOCK STOP-7"
  fi

  section "ssh (existence and fingerprints only)"
  pub="$(ok211::ssh_pubkey)"
  if [ -f "$pub" ]; then
    printf 'pubkey: %s  %s\n' "$(printf '%s' "$pub" | ok211::tilde)" "$(ssh-keygen -lf "$pub" | awk '{print $1, $2}')"
    fp="$(ssh-keygen -lf "$pub" | awk '{print $2}')"
    if ssh-add -l 2>/dev/null | grep -qF "$fp"; then echo "agent: holds the key"; else echo "agent: key not loaded (fine only if the private key has no passphrase)"; fi
  else
    echo "pubkey: MISSING"; echo "BLOCK no SSH public key"
  fi

  section "ports"
  for p in "$TUNNEL_PORT" 6443 6444; do
    holder="$(lsof -nP -iTCP:"$p" -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $1"/"$2}' | sort -u | tr '\n' ' ')"
    printf 'port %s: %s\n' "$p" "${holder:-free}"
  done

  section "kubeconfig isolation"
  printf 'KUBECONFIG: %s\n' "$(printf '%s' "${KUBECONFIG:-<unset>}" | ok211::tilde)"
  [ -f "${KUBECONFIG:-/nonexistent}" ] && echo "kubeconfig file: present" || echo "kubeconfig file: absent"

  section "tools"
  for t in multipass ssh scp curl jq yq helm shellcheck yamllint oras cosign argocd gh kubeconform mmdc; do
    printf '%-12s %s\n' "$t" "$(command -v "$t" 2>/dev/null | ok211::tilde || true)"
  done
  printf '%-12s %s\n' openssl@3 "$(/opt/homebrew/opt/openssl@3/bin/openssl version 2>/dev/null || echo missing)"
  printf '%-12s %s\n' kubectl "$([ -x "$SPIKE_ROOT/.local/bin/kubectl" ] && "$SPIKE_ROOT/.local/bin/kubectl" version --client=true -o json | jq -r .clientVersion.gitVersion || echo 'not pinned yet (make kubectl-pin)')"

  section "local manifests vs. versions.env"
  for line in 1.23 1.24 cert-manager; do
    sums="$SPIKE_ROOT/.local/manifests/$line/SHA256SUMS"
    [ -f "$sums" ] || { printf '%s: not downloaded (make manifests-fetch VERSION=%s)\n' "$line" "$line"; continue; }
    while read -r sha asset; do
      key="MANIFEST_SHA256_$(printf '%s' "$line" | tr 'a-z.-' 'A-Z__')_$(printf '%s' "${asset%.yaml}" | tr 'a-z.-' 'A-Z__')"
      pin="${!key:-}"
      now="$(shasum -a 256 "$SPIKE_ROOT/.local/manifests/$line/$asset" | awk '{print $1}')"
      if [ "$now" = "$pin" ] && [ "$sha" = "$pin" ]; then v=ok; else v="MISMATCH"; echo "BLOCK STOP-4 $line/$asset"; fi
      printf '%s/%s: %s\n' "$line" "$asset" "$v"
    done < "$sums"
  done
} > "$out" 2>&1

blocking="$(grep -E '^BLOCK' "$out" || true)"
cat "$out"
printf '\nraw record: %s\n' "${out#"$SPIKE_ROOT/"}"
if [ -n "$blocking" ]; then
  ok211::error "blocking conditions:"; printf '%s\n' "$blocking" >&2
  exit 1
fi
ok211::ok "preflight: no blocking condition"
