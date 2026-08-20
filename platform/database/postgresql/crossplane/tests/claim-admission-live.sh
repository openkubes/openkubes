#!/usr/bin/env bash
# THE REAL admission test: install the generated DatabaseClaim CRD, the ValidatingAdmissionPolicy
# and its binding on a DISPOSABLE API server, then submit claims with impersonated identities and
# assert the API server's own verdict. Everything else in this repo only models the CEL in Python,
# which cannot catch a compile error, a wrong field path, or an evaluation failure.
# Nothing persists: claims are --dry-run=server and the installed objects are removed on exit.
set -Eeuo pipefail
CTX="${API_CONTEXT:-docker-desktop}"
K="kubectl --context $CTX"
NS=openkubes-system
POLICY=databaseclaim-authority.platform.openkubes.ai
WORK="$(mktemp -d "${TMPDIR:-/tmp}/ok145-admission-XXXXXX")"
INSTALLED=false

cleanup() {
  local rc=$?
  if [[ "$INSTALLED" == true ]]; then
    $K delete -f "$WORK/crds.yaml" --ignore-not-found --wait=false >/dev/null 2>&1 || true
    $K delete -f crossplane/claim-admission-policy.yaml --ignore-not-found --wait=false >/dev/null 2>&1 || true
    $K delete -f crossplane/rbac/claim-editor-binding.yaml --ignore-not-found --wait=false >/dev/null 2>&1 || true
    $K delete -f crossplane/rbac/claim-editor-role.yaml --ignore-not-found --wait=false >/dev/null 2>&1 || true
    $K delete namespace "$NS" --ignore-not-found --wait=false >/dev/null 2>&1 || true
  fi
  rm -rf -- "$WORK"
  exit $rc
}
trap cleanup EXIT

$K get --raw /readyz >/dev/null 2>&1 || {
  echo "SKIPPED: no API server on context $CTX — admission is UNVERIFIED, not OK." >&2; exit 0; }

crossplane xrd convert crossplane/xrd.yaml \
  | python3 -c 'import sys,yaml; docs=list(yaml.safe_load_all(sys.stdin)); [d.get("metadata",{}).pop("ownerReferences",None) for d in docs]; yaml.safe_dump_all(docs,sys.stdout,sort_keys=False)' > "$WORK/crds.yaml"
$K apply -f "$WORK/crds.yaml" >/dev/null
$K create namespace "$NS" --dry-run=client -o yaml | $K apply -f - >/dev/null
$K apply -f crossplane/claim-admission-policy.yaml >/dev/null
$K apply -f crossplane/rbac/claim-editor-role.yaml >/dev/null
$K apply -f crossplane/rbac/claim-editor-binding.yaml >/dev/null
INSTALLED=true
$K wait --for=condition=Established crd/databaseclaims.platform.openkubes.ai --timeout=60s >/dev/null

# The policy must finish type-checking, and MUST report no CEL warnings: a warning here means the
# expressions reference fields the schema does not have, which the Python model cannot detect.
for _ in $(seq 1 20); do
  gen="$($K get validatingadmissionpolicy "$POLICY" -o jsonpath='{.metadata.generation}')"
  obs="$($K get validatingadmissionpolicy "$POLICY" -o jsonpath='{.status.observedGeneration}')"
  [[ "$gen" == "$obs" && -n "$obs" ]] && break
  sleep 2
done
warn="$($K get validatingadmissionpolicy "$POLICY" -o jsonpath='{range .status.typeChecking.expressionWarnings[*]}{.fieldRef}{": "}{.warning}{"\n"}{end}')"
[[ -z "$warn" ]] || { printf 'FAIL: policy has CEL type-check warnings:\n%s\n' "$warn" >&2; exit 1; }
echo "PASS: the API server compiled the policy with no CEL type-check warnings"

can="$($K auth can-i create databaseclaims.platform.openkubes.ai -n "$NS" \
  --as=oidc:probe --as-group=oidc:database-claim-editors --as-group=system:authenticated)"
[[ "$can" == yes ]] || { echo "FAIL: impersonated editor lacks the RBAC verb ($can) — admission would never be reached, and an RBAC denial is not a policy denial" >&2; exit 1; }
echo "PASS: the impersonated editor holds the RBAC verb, so admission is what decides"

AUTH=(--as=oidc:probe --as-group=oidc:database-claim-editors --as-group=system:authenticated)
submit() { # submit <file> <impersonation...>; prints DENIED:<msg> or ADMITTED
  local f="$1"; shift
  local out
  if out="$($K create --dry-run=server -f "$f" "$@" 2>&1)"; then echo "ADMITTED"; else echo "DENIED:$out"; fi
}
mutate() { python3 -c "
import sys,yaml
d=yaml.safe_load(open('crossplane/examples/ok-robotics.yaml'))
import json
for kv in sys.argv[2:]:
    path,val=kv.split('=',1); node=d
    parts=path.split('.')
    for p in parts[:-1]: node=node[p]
    node[parts[-1]]=val
yaml.safe_dump(d,open(sys.argv[1],'w'),sort_keys=False)
" "$1" "${@:2}"; }

fails=0
expect() { # expect <label> <ADMITTED|DENIED> <result>
  local label="$1" want="$2" got="$3"
  if [[ "$want" == ADMITTED && "$got" == ADMITTED ]]; then echo "PASS $label: admitted"; return; fi
  if [[ "$want" == DENIED && "$got" == DENIED:* ]]; then
    if [[ "$got" == *"authorization denied"* || "$got" == *"$POLICY"* ]]; then
      echo "PASS $label: denied by our policy"; return
    fi
    echo "FAIL $label: denied, but not by our policy → ${got:0:160}" >&2; fails=$((fails+1)); return
  fi
  echo "FAIL $label: wanted $want, got ${got:0:160}" >&2; fails=$((fails+1))
}

expect "authorized exact tuple" ADMITTED "$(submit crossplane/examples/ok-robotics.yaml "${AUTH[@]}")"
# Layer 1 — RBAC: a subject outside the editor group never reaches admission at all.
nogroup="$(submit crossplane/examples/ok-robotics.yaml --as=oidc:probe --as-group=system:authenticated)"
if [[ "$nogroup" == DENIED:*forbidden* ]]; then
  echo "PASS ungrouped subject: denied by RBAC before admission (defence in depth)"
else
  echo "FAIL ungrouped subject: wanted an RBAC denial, got ${nogroup:0:120}" >&2; fails=$((fails+1))
fi

# Layer 2 — the POLICY's group check. Grant a decoy group the same verb so RBAC lets it through;
# the tuple list must then be the thing that refuses it. Without this, the group conjunct in
# claimantIsAuthorized is never exercised by any test in this repo.
$K create rolebinding ok145-decoy-editor -n "$NS" --role=database-claim-editor \
  --group=oidc:ok145-decoy-group >/dev/null
decoy_can="$($K auth can-i create databaseclaims.platform.openkubes.ai -n "$NS" \
  --as=oidc:decoy --as-group=oidc:ok145-decoy-group --as-group=system:authenticated)"
[[ "$decoy_can" == yes ]] || { echo "FAIL: decoy group lacks the verb ($decoy_can); the policy group check cannot be tested" >&2; exit 1; }
expect "RBAC-permitted but unauthorized group" DENIED \
  "$(submit crossplane/examples/ok-robotics.yaml --as=oidc:decoy --as-group=oidc:ok145-decoy-group --as-group=system:authenticated)"
$K delete rolebinding ok145-decoy-editor -n "$NS" --ignore-not-found >/dev/null
mutate "$WORK/c1.yaml" spec.clusterRef=ok-shared
expect "wrong clusterRef" DENIED "$(submit "$WORK/c1.yaml" "${AUTH[@]}")"
mutate "$WORK/c2.yaml" spec.namespace=database-elsewhere
expect "wrong namespace"  DENIED "$(submit "$WORK/c2.yaml" "${AUTH[@]}")"
mutate "$WORK/c3.yaml" metadata.name=someone-elses-claim
expect "wrong claim name" DENIED "$(submit "$WORK/c3.yaml" "${AUTH[@]}")"

[[ "$fails" -eq 0 ]] || { echo "FAILURES: $fails" >&2; exit 1; }
echo "OK: real API-server admission — authorized tuple admitted; group, clusterRef, namespace and claim-name deviations each denied by the policy"
