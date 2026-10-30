#!/usr/bin/env bash
# Verify the fetched artifact layer against the named Git tree, including metadata.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
# shellcheck disable=SC1091
. "$ROOT/versions.env"
cd "$ROOT"
umask 077
WORK="$(mktemp -d "$ROOT/.local/tmp/provenance.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
REF="$ZOT_HOST/${REPO:-$REPO_MANIFESTS}:${TAG:-v1.0.0}"
if [ -n "${DIGEST:-}" ]; then REF="$ZOT_HOST/${REPO:-$REPO_MANIFESTS}@$DIGEST"; fi
AUTH="$ROOT/.local/registry-auth/gitops-publisher.json"
"${ORAS:-oras}" manifest fetch "$REF" --ca-file .local/pki/ca.crt --registry-config "$AUTH" > "$WORK/manifest.json"
jq -e '.layers|length==1' "$WORK/manifest.json" >/dev/null
REVISION=$(jq -er '.annotations["org.opencontainers.image.revision"]' "$WORK/manifest.json")
[ "$(git cat-file -t "$REVISION")" = commit ] || ok167::die "revision does not name a commit" 1
TITLE=$(jq -er '.annotations["org.opencontainers.image.title"]' "$WORK/manifest.json")
case "$TITLE" in podinfo-plain|podinfo-plain-update|podinfo-kustomize) : ;; *) ok167::die "unknown source title" 1 ;; esac
SOURCE="architecture/spikes/ADR-Platform-011/OK-167-gitless-gitops/app/$TITLE"
EPOCH=$(git -C "$(git rev-parse --show-toplevel)" log -1 --format=%ct "$REVISION" -- "$SOURCE")
mkdir -p "$WORK/tree"
git -C "$(git rev-parse --show-toplevel)" archive "$REVISION:$SOURCE" \
  | "${GTAR:-gtar}" -xf - -C "$WORK/tree"
"${GTAR:-gtar}" --sort=name --mtime="@$EPOCH" --owner=0 --group=0 --numeric-owner \
  --mode=u=rwX,go=rX --exclude=.DS_Store --format=posix \
  --pax-option=exthdr.name=%d/PaxHeaders/%f,delete=atime,delete=ctime \
  -C "$WORK/tree" -cf - . | gzip -n -9 > "$WORK/expected.gz"
EXPECTED="sha256:$(shasum -a 256 "$WORK/expected.gz" | cut -d' ' -f1)"
LAYER=$(jq -er '.layers[0].digest' "$WORK/manifest.json")
[ "$LAYER" = "$EXPECTED" ] || ok167::die "artifact layer differs from the annotated Git tree" 1
"${ORAS:-oras}" blob fetch "$ZOT_HOST/${REPO:-$REPO_MANIFESTS}@$LAYER" \
  --ca-file .local/pki/ca.crt --registry-config "$AUTH" --output "$WORK/fetched.gz" >/dev/null
cmp "$WORK/expected.gz" "$WORK/fetched.gz" || ok167::die "fetched bytes do not match the reconstructed layer" 1
jq -n --arg revision "$REVISION" --arg layer "$LAYER" --arg source "$SOURCE" \
  '{test:"M3",revision:$revision,source:$source,layer:$layer,bytes_match_git:true,result:"PASS"}'
