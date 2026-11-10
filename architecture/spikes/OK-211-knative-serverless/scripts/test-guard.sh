#!/usr/bin/env bash
#
# OK-211 — guard negative tests (BRIEF B9 Phase 1 step 4).
#
# Runs scripts/guard.sh and ok211::vm_guard against synthetic inputs under
# .local/test/ and checks that each case is refused with the exit code the
# guard documents for exactly that reason. A positive control (a well-formed
# synthetic kubeconfig) must pass, which proves the refusals are caused by the
# defect under test and not by the fixture.
#
# No case contacts a cluster: the node check (--node) is not exercised here.
# The synthetic kubeconfigs hold the placeholder "ZmFrZQ==" ("fake") as data.
#
# Output: a table on stdout and evidence/raw/guard-negative-tests-<stamp>.txt.
# Exit codes: 0 all cases behave as expected, 1 otherwise.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"

T="$SPIKE_ROOT/.local/test"
rm -rf "$T"; mkdir -p "$T"; chmod 700 "$T"
GUARD="${OK211_GUARD_UNDER_TEST:-$SCRIPT_DIR/guard.sh}"
PINNED="$SPIKE_ROOT/.local/bin/kubectl"
[ -x "$PINNED" ] || ok211::die "pinned kubectl missing; run 'make kubectl-pin' first" 2

# kubeconfig <file> <server> <context> [second-context]
kubeconfig() {
  local f="$1" server="$2" ctx="$3" ctx2="${4:-}"
  {
    printf 'apiVersion: v1\nkind: Config\n'
    printf 'clusters:\n- name: ok211\n  cluster:\n    server: %s\n    certificate-authority-data: ZmFrZQ==\n' "$server"
    printf 'contexts:\n- name: %s\n  context:\n    cluster: ok211\n    user: ok211\n' "$ctx"
    [ -n "$ctx2" ] && printf -- '- name: %s\n  context:\n    cluster: ok211\n    user: ok211\n' "$ctx2"
    printf 'current-context: %s\n' "$ctx"
    printf 'users:\n- name: ok211\n  user:\n    client-certificate-data: ZmFrZQ==\n    client-key-data: ZmFrZQ==\n'
  } > "$f"
  chmod 600 "$f"
}

kubeconfig "$T/valid"        "https://127.0.0.1:6450" ok211
kubeconfig "$T/wrong-ctx"    "https://127.0.0.1:6450" kind-ok167
kubeconfig "$T/wrong-server" "https://127.0.0.1:6443" ok211
kubeconfig "$T/userinfo"     "https://127.0.0.1:6450@remote.example:6443" ok211
kubeconfig "$T/two-ctx"      "https://127.0.0.1:6450" ok211 ok-infra-local
kubeconfig "$T/unreadable"   "https://127.0.0.1:6450" ok211; chmod 000 "$T/unreadable"
awk '{print} /certificate-authority-data/{print "    insecure-skip-tls-verify: true"}' "$T/valid" > "$T/insecure"
chmod 600 "$T/insecure"
# A symlink inside .local/ whose target is outside it (OK-167 hurdle C5). The
# target is a harmless tracked file of this spike; the guard must refuse it
# before reading it.
ln -s "$SPIKE_ROOT/versions.env" "$T/link-outside"

results="$T/results.tsv"; : > "$results"
fail=0

# run_case <id> <description> <expected-exit> <env assignments...> -- <command...>
run_case() {
  local id="$1" desc="$2" want="$3"; shift 3
  local envs=()
  while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do envs+=("$1"); shift; done
  shift
  local errf="$T/$id.err" rc
  env -i HOME="$HOME" PATH="$PATH" ${envs[@]+"${envs[@]}"} "$@" >/dev/null 2>"$errf"; rc=$?
  local msg; msg="$(grep -E 'FAIL|PASS' "$errf" | head -1 | sed -E 's/^.*(FAIL|PASS) //' | ok211::tilde)"
  local verdict=PASS
  [ "$rc" = "$want" ] || { verdict=FAIL; fail=1; }
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$id" "$desc" "$want" "$rc" "$verdict" "$msg" >> "$results"
}

K="KUBECTL=$PINNED"
run_case C0  "positive control: valid synthetic kubeconfig" 0  "$K" "KUBECONFIG=$T/valid" -- "$GUARD"
run_case N1  "KUBECONFIG empty"                              10 "$K" "KUBECONFIG=" -- "$GUARD"
run_case N2  "path outside .local/ (traversal via ..)"       12 "$K" "KUBECONFIG=$T/../../versions.env" -- "$GUARD"
run_case N3  "file does not exist"                           13 "$K" "KUBECONFIG=$T/missing" -- "$GUARD"
run_case N4  "wrong context name (kind-ok167)"               15 "$K" "KUBECONFIG=$T/wrong-ctx" -- "$GUARD"
run_case N5  "server :6443 (an ok-local tunnel port)"        16 "$K" "KUBECONFIG=$T/wrong-server" -- "$GUARD"
run_case N6  "two contexts"                                  14 "$K" "KUBECONFIG=$T/two-ctx" -- "$GUARD"
run_case N7  "symlink in .local/ pointing outside"           12 "$K" "KUBECONFIG=$T/link-outside" -- "$GUARD"
run_case N8  "unreadable kubeconfig (mode 000)"              18 "$K" "KUBECONFIG=$T/unreadable" -- "$GUARD"
run_case N9  "kubectl from PATH instead of .local/bin/"      19 "KUBECTL=/usr/local/bin/kubectl" "KUBECONFIG=$T/valid" -- "$GUARD"
run_case N10 "vm_guard with VM_NAME=ok-infra-local"          30 "VM_NAME=ok-infra-local" -- bash -c ". '$SCRIPT_DIR/lib.sh'; ok211::vm_guard"
# Additional cases beyond the ten the BRIEF requires.
run_case X1  "server with userinfo (127.0.0.1:6450@remote)"  16 "$K" "KUBECONFIG=$T/userinfo" -- "$GUARD"
run_case X2  "insecure-skip-tls-verify: true"                16 "$K" "KUBECONFIG=$T/insecure" -- "$GUARD"
run_case X3  "kubectl resolved by name from a PATH without .local/bin" 19 "KUBECTL=kubectl" "KUBECONFIG=$T/valid" -- env PATH=/usr/local/bin:/usr/bin:/bin "$GUARD"
run_case X4  "vm_guard with VM_NAME unset"                   30 -- bash -c ". '$SCRIPT_DIR/lib.sh'; ok211::vm_guard"
run_case X5  "vm_guard with VM_NAME=ok-knative-local (positive control)" 0 "VM_NAME=ok-knative-local" -- bash -c ". '$SCRIPT_DIR/lib.sh'; ok211::vm_guard"

chmod 600 "$T/unreadable"

out="$SPIKE_ROOT/evidence/raw/guard-negative-tests-$(ok211::stamp).txt"
{
  printf '# OK-211 guard negative tests — %s — commit %s\n' "$(ok211::timestamp)" "$(git -C "$SPIKE_ROOT" rev-parse --short HEAD)"
  printf 'id\tcase\texpected_exit\tactual_exit\tverdict\tguard_message\n'
  cat "$results"
} > "$out"
column -t -s "$(printf '\t')" < "$out"
printf '\nraw record: %s\n' "${out#"$SPIKE_ROOT/"}"
if [ "$fail" -ne 0 ]; then ok211::error "guard tests: at least one case did not behave as expected"; exit 1; fi
ok211::ok "guard tests: all cases behave as expected"
