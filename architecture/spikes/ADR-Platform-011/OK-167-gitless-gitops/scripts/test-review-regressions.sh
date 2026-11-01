#!/usr/bin/env bash
# Offline adversarial tests for PR #462. Fixtures stay inside ignored .local/.
# shellcheck disable=SC2120,SC2119  # callback arguments are passed by expect_exit
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
KUBECTL="${KUBECTL:-/opt/homebrew/bin/kubectl}"
GTAR="${GTAR:-gtar}"
umask 077
mkdir -p "$ROOT/.local/tmp"
WORK="$(mktemp -d "$ROOT/.local/tmp/review-tests.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
REL=architecture/spikes/ADR-Platform-011/OK-167-gitless-gitops
FIXTURE="$WORK/repository/$REL"
mkdir -p "$FIXTURE"
# Copy only the test inputs; never copy the host's credentials or kubeconfig.
for path in scripts app ci versions.env .yamllint.yaml .gitignore; do
  cp -R "$ROOT/$path" "$FIXTURE/"
done
git -C "$WORK/repository" init -q --initial-branch=review-fixture
git -C "$WORK/repository" add "$REL"
git -C "$WORK/repository" -c user.name='Regression Fixture' -c user.email=fixture@example.invalid \
  commit -qm 'test(gitops): create isolated regression fixture (OK-167)'
cd "$FIXTURE"
mkdir -p .local/test
PASS=0
FAIL=0
expect_exit() {
  local name="$1" expected="$2" actual=0
  shift 2
  "$@" > "$WORK/output" 2>&1 || actual=$?
  if [ "$actual" = "$expected" ]; then
    jq -nc --arg name "$name" --argjson exit "$actual" '{test:$name,result:"PASS",exit:$exit}'
    PASS=$(( PASS + 1 ))
  else
    jq -nc --arg name "$name" --argjson exit "$actual" --argjson expected "$expected" \
      '{test:$name,result:"FAIL",exit:$exit,expected:$expected}'
    FAIL=$(( FAIL + 1 ))
  fi
}
config() {
  jq -n --arg server "$1" '{apiVersion:"v1",kind:"Config", "current-context":"kind-ok167",
    contexts:[{name:"kind-ok167",context:{cluster:"kind-ok167",user:"fixture"}}],
    clusters:[{name:"kind-ok167",cluster:{server:$server}}],
    users:[{name:"fixture",user:{token:"synthetic"}}]}' > .local/test/kubeconfig
}
config https://127.0.0.1:62345
export KUBECONFIG="$PWD/.local/test/kubeconfig" KUBECTL
expect_exit guard-valid 0 scripts/guard.sh
for server in https://127.0.0.1:443@remote.invalid:6443 https://127.0.0.1:6443/path \
              https://127.0.0.1:65536 https://remote.invalid:6443; do
  config "$server"
  expect_exit "guard-reject-$server" 16 scripts/guard.sh
done
for field in proxy-url certificate-authority tls-server-name; do
  config https://127.0.0.1:62345
  jq --arg field "$field" '.clusters[0].cluster[$field]="outside"' \
    .local/test/kubeconfig > .local/test/next
  mv .local/test/next .local/test/kubeconfig
  expect_exit "guard-reject-$field" 16 scripts/guard.sh
done
config https://127.0.0.1:62345
jq '.clusters[0].cluster["insecure-skip-tls-verify"]=true' \
  .local/test/kubeconfig > .local/test/next
mv .local/test/next .local/test/kubeconfig
expect_exit guard-reject-insecure 16 scripts/guard.sh
for field in exec auth-provider client-key client-certificate tokenFile; do
  config https://127.0.0.1:62345
  jq --arg field "$field" '.users[0].user[$field] =
    (if $field == "exec" then {apiVersion:"client.authentication.k8s.io/v1",command:"never-execute",interactiveMode:"Never"}
     elif $field == "auth-provider" then {name:"never-execute"} else "outside" end)' \
    .local/test/kubeconfig > .local/test/next
  mv .local/test/next .local/test/kubeconfig
  expect_exit "guard-reject-$field" 16 scripts/guard.sh
done
config https://127.0.0.1:62345
cp .local/test/kubeconfig "$WORK/outside-kubeconfig"
ln -s "$WORK/outside-kubeconfig" .local/test/link
expect_exit guard-reject-symlink 12 env KUBECONFIG="$PWD/.local/test/link" scripts/guard.sh
expect_exit guard-reject-unset 10 env KUBECONFIG= scripts/guard.sh
expect_exit guard-reject-multipath 11 env KUBECONFIG="$KUBECONFIG:$KUBECONFIG" scripts/guard.sh

config https://127.0.0.1:62345
jq '.contexts += [{name:"second",context:{cluster:"kind-ok167",user:"fixture"}}]' .local/test/kubeconfig > .local/test/next
mv .local/test/next .local/test/kubeconfig
expect_exit guard-reject-two-contexts 14 scripts/guard.sh
config https://127.0.0.1:62345
jq '."current-context"="foreign" | .contexts[0].name="foreign"' .local/test/kubeconfig > .local/test/next
mv .local/test/next .local/test/kubeconfig
expect_exit guard-reject-context 15 scripts/guard.sh
expect_exit guard-reject-relative 11 env KUBECONFIG=.local/test/kubeconfig scripts/guard.sh
expect_exit guard-reject-missing 13 env KUBECONFIG="$PWD/.local/test/missing" scripts/guard.sh
expect_exit guard-reject-traversal 12 env KUBECONFIG="$PWD/.local/../../../outside" scripts/guard.sh

package() {
  scripts/package-and-push.sh --source app/podinfo-plain --repository review --tag review --dry-run "$@"
}
expect_exit package-clean 0 package
BASE="$(package 2>/dev/null)"
printf 'uncommitted payload\n' > app/podinfo-plain/ignored.pem
expect_exit package-reject-ignored 2 package
expect_exit package-explicit-dirty 0 package --allow-dirty
rm app/podinfo-plain/ignored.pem
chmod u-w app/podinfo-plain/deployment.yaml
expect_exit package-readonly 0 package
AFTER="$(package 2>/dev/null)"
expect_exit package-readonly-same-digest 0 test "$BASE" = "$AFTER"
chmod u+w app/podinfo-plain/deployment.yaml
git update-index --assume-unchanged app/podinfo-plain/deployment.yaml
sed 's/replicas: 1/replicas: 7/' app/podinfo-plain/deployment.yaml > .local/test/modified
cp .local/test/modified app/podinfo-plain/deployment.yaml
expect_exit package-reject-assume-unchanged 2 package
git update-index --no-assume-unchanged app/podinfo-plain/deployment.yaml
git checkout -- app/podinfo-plain/deployment.yaml

# Build dummy credential values at runtime so the scanner can scan this test.
opaque="$(printf 'Fixture%s' 'Credential987654321')"
for prefix in '' '$' '<'; do
  suffix=''
  [ "$prefix" != '<' ] || suffix='>'
  printf 'password: %s%s%s\n' "$prefix" "$opaque" "$suffix" > tripwire.yaml
  expect_exit "scanner-literal-$prefix" 1 scripts/scan-secrets.sh
  rm tripwire.yaml
done
printf 'password: %s\n' "$opaque" > tripwire.yaml
git add tripwire.yaml
printf 'password: <redacted>\n' > tripwire.yaml
expect_exit scanner-staged-secret 1 scripts/scan-secrets.sh
rm tripwire.yaml
expect_exit scanner-staged-secret-missing-worktree 1 scripts/scan-secrets.sh
git reset -q HEAD -- tripwire.yaml
printf 'OK167_GITOPS_PULLER_PASSWORD=%s\n' "$opaque" > .local/credentials.env
cat > "$WORK/jq-argv-check" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
for arg; do [ "$arg" != "$EXPECTED_FIXTURE_CREDENTIAL" ] || exit 91; done
exec /usr/bin/jq "$@"
STUB
chmod +x "$WORK/jq-argv-check"
expect_exit secret-absent-from-jq-argv 0 env JQ="$WORK/jq-argv-check" \
  EXPECTED_FIXTURE_CREDENTIAL="$opaque" scripts/repository-secret.sh repository fixture
rm .local/credentials.env
cat > "$WORK/kubectl-measurement-fixture" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  *' get cm '*) printf '%s\n' '{"data":{"timeout.reconciliation":"120s","timeout.reconciliation.jitter":"60s"}}' ;;
  *) printf '%s\n' '{"status":{"sync":{"revision":"old","status":"Synced"},"health":{"status":"Healthy"}}}' ;;
esac
STUB
chmod +x "$WORK/kubectl-measurement-fixture"
expect_exit measurement-timeout-is-failure 1 env KUBECTL="$WORK/kubectl-measurement-fixture" \
  scripts/measure-sync.sh --app fixture --digest expected --namespace fixture --timeout 1
expect_exit measurement-timeout-record-retained 0 jq -e \
  '.result=="TIMEOUT" and (.timestamps.t0|type)=="number"' evidence/raw/measurements.json
printf '\000binary fixture\000' > tripwire.key
git add -f tripwire.key
expect_exit scanner-forbidden-binary-key 1 scripts/scan-secrets.sh
git reset -q HEAD -- tripwire.key
rm tripwire.key
mkdir -p "$WORK/gnu-bin"
ln -s "$(command -v "$GTAR")" "$WORK/gnu-bin/tar"
expect_exit ci-gnu-tar-binary-name 0 env PATH="$WORK/gnu-bin:/usr/bin:/bin" GTAR=tar \
  ORAS="$(command -v oras)" YAMLLINT="$(command -v yamllint)" \
  scripts/package-and-push.sh --source app/podinfo-plain --repository review --tag review --dry-run
expect_exit scanner-clean 0 scripts/scan-secrets.sh
jq -nc --argjson passed "$PASS" --argjson failed "$FAIL" '{summary:{passed:$passed,failed:$failed}}'
[ "$FAIL" = 0 ]
