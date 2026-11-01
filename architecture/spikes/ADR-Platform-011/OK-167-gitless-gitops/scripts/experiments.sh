#!/usr/bin/env bash
# Guarded experiment implementations. Invoke them only through the Make targets.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
# shellcheck disable=SC1091
. "$ROOT/versions.env"
cd "$ROOT"
CASE="${1:?experiment required}"
KUBECTL="${KUBECTL:-kubectl}"
ORAS="${ORAS:-oras}"
AUTH="$ROOT/.local/registry-auth/gitops-publisher.json"
CA="$ROOT/.local/pki/ca.crt"
REG="$ZOT_HOST/$REPO_MANIFESTS"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="evidence/raw/retest-$CASE-$STAMP.json"
umask 077
WORK="$(mktemp -d "$ROOT/.local/tmp/experiment.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
oras_auth() { "$ORAS" "$@" --ca-file "$CA" --registry-config "$AUTH"; }
wait_app() { scripts/wait-application.sh "$1" "${2:-}" "${3:-300}"; }
wait_error() {
  local app="$1" pattern="$2" deadline
  deadline=$(( $(ok167::epoch) + 180 ))
  while [ "$(ok167::epoch)" -lt "$deadline" ]; do
    "$KUBECTL" -n argocd get application "$app" -o json \
      | jq '{app:.metadata.name,conditions:.status.conditions,sync:.status.sync}' > "$WORK/error.json"
    if jq -er '[.conditions[]?.message]|join(" ")' "$WORK/error.json" | grep -qi "$pattern"; then
      cp "$WORK/error.json" "$OUT"
      return 0
    fi
    sleep 1
  done
  ok167::die "expected Application error was not observed" 1
}
restore_auth() {
  make --no-print-directory argocd-repo REPO=podinfo-manifests >/dev/null
  make --no-print-directory repo-server-restart refresh APP=ok167-podinfo-tag HARD=1 >/dev/null
}
restore_ca() {
  make --no-print-directory argocd-install repo-server-restart refresh APP=ok167-podinfo-tag HARD=1 >/dev/null
}
case "$CASE" in
  q1b)
    d=$(make --no-print-directory push VARIANT=kustomize TAG=v1.0.0 | sed -n 's/^DIGEST=//p')
    make --no-print-directory argocd-repo-creds app-kustomize >/dev/null
    wait_app ok167-podinfo-kustomize "$d" > "$WORK/app.json"
    "$KUBECTL" -n argocd get secrets -l argocd.argoproj.io/secret-type=repository \
      -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' > "$WORK/exact-names.txt"
    if grep -q 'kustomize' "$WORK/exact-names.txt"; then ok167::die "unexpected exact Kustomize repository Secret" 1; fi
    jq -n --slurpfile app "$WORK/app.json" --rawfile names "$WORK/exact-names.txt" \
      '{test:"Q1.b",exact_repository_secret_names:($names|split("\n")|map(select(length>0))),
        prefix_template:"ok167-zot-prefix",application:$app[0],result:"PASS"}' > "$OUT"
    ;;
  self-heal)
    t0=$(jq -nr 'now * 1000 | floor')
    make --no-print-directory drift NS=ok167-kustomize >/dev/null
    command_returned=$(jq -nr 'now * 1000 | floor')
    deadline=$(( $(ok167::epoch) + 60 ))
    replicas=''
    while [ "$(ok167::epoch)" -lt "$deadline" ]; do
      replicas=$("$KUBECTL" -n ok167-kustomize get deployment podinfo -o jsonpath='{.spec.replicas}')
      [ "$replicas" != 2 ] || break
      sleep 1
    done
    [ "$replicas" = 2 ] || ok167::die "self-heal did not restore two replicas" 1
    t1=$(jq -nr 'now * 1000 | floor')
    wait_app ok167-podinfo-kustomize > "$WORK/app.json"
    jq -n --argjson t0 "$t0" --argjson returned "$command_returned" --argjson t1 "$t1" --slurpfile app "$WORK/app.json" \
      '{test:"T7",timestamps_ms:{invocation_start:$t0,scale_returned:$returned,restored:$t1},
        seconds_from_scale_return:(($t1-$returned)/1000),replicas:2,application:$app[0],result:"PASS"}' > "$OUT"
    ;;
  q1c)
    trap 'restore_auth; rm -rf "$WORK"' EXIT
    make --no-print-directory argocd-repo REPO=podinfo-manifests WRONG_PASSWORD=1 >/dev/null
    make --no-print-directory repo-server-restart refresh APP=ok167-podinfo-tag HARD=1 >/dev/null
    wait_error ok167-podinfo-tag '401'
    restore_auth
    wait_app ok167-podinfo-tag > "$WORK/restored.json"
    jq -n --slurpfile failure "$OUT" --slurpfile recovery "$WORK/restored.json" \
      '{test:"Q1.c",failure:$failure[0],recovery:$recovery[0],result:"PASS"}' > "$WORK/result.json"
    cp "$WORK/result.json" "$OUT"
    trap 'rm -rf "$WORK"' EXIT
    ;;
  q1d)
    trap 'restore_ca; rm -rf "$WORK"' EXIT
    make --no-print-directory argocd-without-ca repo-server-restart refresh APP=ok167-podinfo-tag HARD=1 >/dev/null
    wait_error ok167-podinfo-tag 'x509'
    restore_ca
    wait_app ok167-podinfo-tag > "$WORK/restored.json"
    jq -n --slurpfile failure "$OUT" --slurpfile recovery "$WORK/restored.json" \
      '{test:"Q1.d",failure:$failure[0],recovery:$recovery[0],result:"PASS"}' > "$WORK/result.json"
    cp "$WORK/result.json" "$OUT"
    trap 'rm -rf "$WORK"' EXIT
    ;;
  structure)
    git -C "$(git rev-parse --show-toplevel)" archive "HEAD:architecture/spikes/ADR-Platform-011/OK-167-gitless-gitops/app/podinfo-plain" \
      | "${GTAR:-gtar}" -xf - -C "$WORK"
    "${GTAR:-gtar}" -C "$WORK" -czf "$WORK/first.tar.gz" deployment.yaml service.yaml
    cp "$WORK/first.tar.gz" "$WORK/second.tar.gz"
    REVISION="$(git rev-parse HEAD)"
    for variant in two-layers not-archive; do
      case "$variant" in
        two-layers) FILES=(first.tar.gz:application/vnd.oci.image.layer.v1.tar+gzip second.tar.gz:application/vnd.oci.image.layer.v1.tar+gzip); ERROR='single oci content layer, got 2' ;;
        not-archive) FILES=(deployment.yaml:application/yaml); ERROR='single oci content layer, got 0' ;;
      esac
      (cd "$WORK" && oras_auth push "$ZOT_HOST/$REPO_PREFIX/negative/$variant:review" "${FILES[@]}" \
        --annotation "org.opencontainers.image.source=https://github.com/openkubes/openkubes" \
        --annotation "org.opencontainers.image.revision=$REVISION") >/dev/null
      make --no-print-directory app-negative CASE_ID="$variant" >/dev/null
      wait_error "ok167-negative-$variant" "$ERROR"
      cp "$OUT" "$WORK/$variant.json"
    done
    jq -n --slurpfile two "$WORK/two-layers.json" --slurpfile none "$WORK/not-archive.json" \
      '{test:"S-E/S-F",two_layers:$two[0],non_archive:$none[0],result:"PASS"}' > "$OUT"
    ;;
  latency)
    # Establish immutable-tag and digest baselines before the changing-tag trials.
    d=$(make --no-print-directory push VARIANT=plain TAG=release-review | sed -n 's/^DIGEST=//p')
    make --no-print-directory app-exact app-digest DIGEST="$d" >/dev/null
    wait_app ok167-podinfo-exact "$d" > "$WORK/exact-start.json"
    wait_app ok167-podinfo-digest "$d" > "$WORK/digest-start.json"
    PIN_START=$(ok167::epoch)
    base=$(make --no-print-directory push VARIANT=plain TAG=v1.0.0 | sed -n 's/^DIGEST=//p')
    make --no-print-directory app-tag refresh APP=ok167-podinfo-tag HARD=1 >/dev/null
    wait_app ok167-podinfo-tag "$base" >/dev/null
    for run in 1 2 3; do
      if [ "$run" = 2 ]; then variant=plain; image="$PODINFO_IMAGE_REPOSITORY:$PODINFO_VERSION_A@$PODINFO_DIGEST_A";
      else variant=plain-update; image="$PODINFO_IMAGE_REPOSITORY:$PODINFO_VERSION_B@$PODINFO_DIGEST_B"; fi
      changed=$(make --no-print-directory push VARIANT="$variant" TAG=v1.0.0 | sed -n 's/^DIGEST=//p')
      t0=$(ok167::epoch)
      # No refresh, restart or source mutation between this push and measurement.
      make --no-print-directory measure APP=ok167-podinfo-tag DIGEST="$changed" IMAGE="$image" \
        T0="$t0" LABEL="retest-T1-run$run"
    done
    for run in 1 2 3; do
      if [ "$run" = 2 ]; then variant=plain-update; image="$PODINFO_IMAGE_REPOSITORY:$PODINFO_VERSION_B@$PODINFO_DIGEST_B";
      else variant=plain; image="$PODINFO_IMAGE_REPOSITORY:$PODINFO_VERSION_A@$PODINFO_DIGEST_A"; fi
      changed=$(make --no-print-directory push VARIANT="$variant" TAG=v1.0.0 | sed -n 's/^DIGEST=//p')
      t0=$(ok167::epoch)
      make --no-print-directory refresh APP=ok167-podinfo-tag >/dev/null
      make --no-print-directory measure APP=ok167-podinfo-tag DIGEST="$changed" IMAGE="$image" \
        T0="$t0" LABEL="retest-T2-run$run"
    done
    while [ "$(( $(ok167::epoch) - PIN_START ))" -lt 360 ]; do sleep 1; done
    wait_app ok167-podinfo-exact "$d" > "$WORK/exact-end.json"
    wait_app ok167-podinfo-digest "$d" > "$WORK/digest-end.json"
    jq -n --arg digest "$d" --argjson start "$PIN_START" --argjson end "$(ok167::epoch)" \
      --slurpfile exact_start "$WORK/exact-start.json" --slurpfile exact_end "$WORK/exact-end.json" \
      --slurpfile digest_start "$WORK/digest-start.json" --slurpfile digest_end "$WORK/digest-end.json" \
      '{test:"T3/T4",retained_tag:"release-review",expected_digest:$digest,start:$start,end:$end,
        seconds:($end-$start),exact_tag:{before:$exact_start[0],after:$exact_end[0]},
        digest_pin:{before:$digest_start[0],after:$digest_end[0]},result:"PASS"}' > "$OUT"
    ;;
  signing)
    signed=$(make --no-print-directory push VARIANT=plain-update TAG=signed-review | sed -n 's/^DIGEST=//p')
    make --no-print-directory sign DIGEST="$signed" MODE=bundle > "$WORK/sign.json"
    make --no-print-directory verify-signature DIGEST="$signed" MODE=bundle > "$WORK/verify.json"
    unsigned=$(make --no-print-directory push VARIANT=plain TAG=unsigned-review | sed -n 's/^DIGEST=//p')
    oras_auth discover "$REG@$unsigned" --format json > "$WORK/unsigned-referrers.json"
    jq -e '(.referrers // [])|length==0' "$WORK/unsigned-referrers.json" >/dev/null
    oras_auth repo tags "$REG" --format json > "$WORK/tags.json"
    legacy_tag="sha256-${unsigned#sha256:}.sig"
    # Check both signature formats before calling the source unsigned.
    if jq -r '.tags[]' "$WORK/tags.json" | grep -qx "$legacy_tag"; then
      ok167::die "the unsigned test digest has a legacy signature tag" 1
    fi
    make --no-print-directory app-set-revision APP=ok167-podinfo-tag REV=unsigned-review >/dev/null
    make --no-print-directory refresh APP=ok167-podinfo-tag HARD=1 >/dev/null
    wait_app ok167-podinfo-tag "$unsigned" > "$WORK/unsigned-app.json"
    failed=0
    make --no-print-directory verify-signature DIGEST="$unsigned" MODE=bundle > "$WORK/rejected.log" 2>&1 || failed=$?
    [ "$failed" -ne 0 ] || ok167::die "unsigned verification unexpectedly succeeded" 1
    jq -n --arg signed "$signed" --arg unsigned "$unsigned" \
      --slurpfile sign "$WORK/sign.json" --slurpfile verify "$WORK/verify.json" \
      --slurpfile app "$WORK/unsigned-app.json" --slurpfile refs "$WORK/unsigned-referrers.json" \
      '{test:"Q4/K2",signed_digest:$signed,unsigned_digest:$unsigned,signing:$sign[0],
        verification:$verify[0],unsigned_referrers:$refs[0],unsigned_has_legacy_tag:false,
        unsigned_verification_rejected:true,unsigned_application:$app[0],K2:"NOT MET"}' > "$OUT"
    printf 'SIGNED_DIGEST=%s\n' "$signed"
    ;;
  recovery)
    # Cache-cold outage and recovery; do not refresh after zot is restored.
    trap 'make --no-print-directory zot-up >/dev/null; rm -rf "$WORK"' EXIT
    "$KUBECTL" -n ok167-demo get pods -l app.kubernetes.io/name=podinfo -o json \
      | jq '[.items[]|{name:.metadata.name,phase:.status.phase,restarts:[.status.containerStatuses[].restartCount]}]' > "$WORK/pods-before.json"
    make --no-print-directory zot-down repo-server-restart refresh APP=ok167-podinfo-tag HARD=1 >/dev/null
    wait_error ok167-podinfo-tag 'ComparisonError\|deadline\|connect\|unavailable'
    cp "$OUT" "$WORK/failure.json"
    make --no-print-directory zot-up >/dev/null
    t0=$(jq -nr 'now * 1000 | floor')
    wait_app ok167-podinfo-tag > "$WORK/recovered.json"
    t1=$(jq -nr 'now * 1000 | floor')
    "$KUBECTL" -n ok167-demo get pods -l app.kubernetes.io/name=podinfo -o json \
      | jq '[.items[]|{name:.metadata.name,phase:.status.phase,restarts:[.status.containerStatuses[].restartCount]}]' > "$WORK/pods-after.json"
    jq -n --argjson t0 "$t0" --argjson t1 "$t1" --slurpfile error "$WORK/failure.json" \
      --slurpfile recovery "$WORK/recovered.json" --slurpfile before "$WORK/pods-before.json" --slurpfile after "$WORK/pods-after.json" \
      '{test:"T8",timestamps_ms:{registry_ready:$t0,recovered:$t1},seconds:(($t1-$t0)/1000),
        refresh_after_restore:false,error:$error[0],recovery:$recovery[0],
        pods_before:$before[0],pods_after:$after[0],result:"PASS"}' > "$OUT"
    trap 'rm -rf "$WORK"' EXIT
    ;;
  offline)
    DIGEST="${DIGEST:?DIGEST required}"
    LAYOUT="$ROOT/.local/offline-review/$STAMP"
    mkdir -p "$LAYOUT"
    "$ORAS" cp -r "$REG@$DIGEST" --to-oci-layout "$LAYOUT:exported" \
      --from-ca-file "$CA" --from-registry-config "$AUTH" > "$WORK/copy.log" 2>&1
    "$ORAS" cp -r --from-oci-layout "$LAYOUT@$DIGEST" "$ZOT_HOST/$REPO_IMPORTED:review" \
      --to-ca-file "$CA" --to-registry-config "$AUTH" >> "$WORK/copy.log" 2>&1
    make --no-print-directory app-imported DIGEST="$DIGEST" >/dev/null
    wait_app ok167-podinfo-imported "$DIGEST" > "$WORK/application.json"
    make --no-print-directory verify-signature DIGEST="$DIGEST" REPO="$REPO_IMPORTED" > "$WORK/verification.json"
    oras_auth discover "$ZOT_HOST/$REPO_IMPORTED@$DIGEST" --format json > "$WORK/referrers.json"
    jq -e '.referrers|length>0' "$WORK/referrers.json" >/dev/null
    jq -n --arg digest "$DIGEST" --slurpfile app "$WORK/application.json" \
      --slurpfile verification "$WORK/verification.json" --slurpfile refs "$WORK/referrers.json" \
      '{test:"K4",digest:$digest,application:$app[0],verification:$verification[0],referrers:$refs[0],result:"PASS"}' > "$OUT"
    ;;
  *) ok167::die "unknown experiment" 2 ;;
esac
ok167::ok "$CASE evidence: $OUT"
