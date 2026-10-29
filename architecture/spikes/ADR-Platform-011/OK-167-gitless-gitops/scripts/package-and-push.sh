#!/usr/bin/env bash
#
# OK-167 — package Kubernetes manifests as a single-layer OCI artifact and push
# it to zot. This is deliverable D1.
#
# Usage:
#   package-and-push.sh --source <dir> --repository <repo> --tag <tag>
#                       [--registry <host:port>] [--allow-dirty] [--dry-run]
#
#   --source       directory whose contents become the artifact (packed at its root)
#   --repository   repository path inside the registry, e.g. openkubes/machine/gitops/podinfo-manifests
#   --tag          tag to push
#   --registry     default: $ZOT_HOST from versions.env
#   --allow-dirty  package even though the source directory has uncommitted changes,
#                  and record io.openkubes.source.dirty=true
#   --dry-run      package and report the layer digest, push nothing
#
# Provenance is the point. Git stays the source of truth (ADR-011 section 1) and
# the registry is only the delivery channel, so every artifact must lead back to
# a commit: org.opencontainers.image.source and .revision carry that, and the
# archive is built deterministically so the same input yields the same digest.
#
# Determinism requires GNU tar: macOS bsdtar cannot sort entries by name, so the
# member order — and therefore the digest — would depend on directory order.
#
# Portability: bash 3.2 (macOS ships nothing newer).
#
# Exit codes
#   0  success
#   2  validation failed (bad arguments, dirty tree, yamllint, kustomize)
#   3  authentication failed
#   4  push failed

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck source=./lib.sh
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib.sh"
# shellcheck disable=SC1091
. "$SPIKE_ROOT/versions.env"

ORAS="${ORAS:-oras}"
GTAR="${GTAR:-gtar}"
YAMLLINT="${YAMLLINT:-yamllint}"
KUBECTL="${KUBECTL:-kubectl}"
JQ="${JQ:-jq}"

SOURCE=""
REPOSITORY=""
TAG=""
REGISTRY="${ZOT_HOST:-127.0.0.1:30500}"
ALLOW_DIRTY=0
DRY_RUN=0

SOURCE_URL="https://github.com/openkubes/openkubes"
ARTIFACT_TYPE="application/vnd.openkubes.gitops.manifests.v1+tar"
LAYER_MEDIA_TYPE="application/vnd.oci.image.layer.v1.tar+gzip"
IDENTITY="${IDENTITY_PUBLISHER:-gitops-publisher}"

usage() { sed -n '3,25p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --source)      SOURCE="${2:-}"; shift 2 ;;
    --repository)  REPOSITORY="${2:-}"; shift 2 ;;
    --tag)         TAG="${2:-}"; shift 2 ;;
    --registry)    REGISTRY="${2:-}"; shift 2 ;;
    --allow-dirty) ALLOW_DIRTY=1; shift ;;
    --dry-run)     DRY_RUN=1; shift ;;
    -h|--help)     usage; exit 0 ;;
    *) ok167::die "unknown argument: $1" 2 ;;
  esac
done

[ -n "$SOURCE" ]     || ok167::die "--source is required" 2
[ -n "$REPOSITORY" ] || ok167::die "--repository is required" 2
[ -n "$TAG" ]        || ok167::die "--tag is required" 2

cd "$SPIKE_ROOT"

ok167::require_tool "$ORAS"
ok167::require_tool "$GTAR"
ok167::require_tool "$JQ"
ok167::require_dir "$SOURCE" "source directory"

# GNU tar is not optional — see the header.
"$GTAR" --version | head -1 | grep -q 'GNU tar' \
  || ok167::die "$GTAR is not GNU tar; macOS bsdtar cannot sort archive members" 2

CA="$SPIKE_ROOT/.local/pki/ca.crt"
AUTH="$SPIKE_ROOT/.local/registry-auth/$IDENTITY.json"
CREDS="$SPIKE_ROOT/.local/credentials.env"

# ---------------------------------------------------------------------------
# 1. Provenance
# ---------------------------------------------------------------------------
GIT_SHA="$(git rev-parse HEAD)"

# The timestamp of the last commit that touched the source directory. Using the
# current time would make every build produce a different digest.
SOURCE_DATE_EPOCH="$(git log -1 --format=%ct -- "$SOURCE" || true)"
[ -n "$SOURCE_DATE_EPOCH" ] \
  || ok167::die "no commit found for $SOURCE — commit the manifests before packaging" 2

# Dirty tree check, scoped to the source directory.
DIRTY=0
if [ -n "$(git status --porcelain -- "$SOURCE")" ]; then
  if [ "$ALLOW_DIRTY" -eq 1 ]; then
    DIRTY=1
    ok167::warn "$SOURCE has uncommitted changes; packaging anyway (--allow-dirty)"
  else
    ok167::error "$SOURCE has uncommitted changes."
    ok167::error "The revision annotation would point at a commit with different content."
    ok167::error "Commit the manifests, or pass --allow-dirty to record the artifact as dirty."
    exit 2
  fi
fi

# RFC 3339 from the epoch, so .created is deterministic too. BSD date and GNU
# date disagree on the flag, so both are tried.
CREATED="$(date -u -r "$SOURCE_DATE_EPOCH" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
  || date -u -d "@$SOURCE_DATE_EPOCH" +%Y-%m-%dT%H:%M:%SZ)"

# ---------------------------------------------------------------------------
# 2. Validation
# ---------------------------------------------------------------------------
ok167::info "validating $SOURCE"

if command -v "$YAMLLINT" >/dev/null 2>&1; then
  "$YAMLLINT" -c "$SPIKE_ROOT/.yamllint.yaml" "$SOURCE" \
    || ok167::die "yamllint failed for $SOURCE" 2
fi

# Every directory in the artifact that carries a kustomization.yaml must build.
# A broken overlay would otherwise only surface as an Argo CD sync error, long
# after the artifact was published.
while IFS= read -r kdir; do
  [ -n "$kdir" ] || continue
  ok167::info "kustomize build $kdir"
  "$KUBECTL" kustomize "$kdir" >/dev/null \
    || ok167::die "kustomize build failed for $kdir" 2
done < <(find "$SOURCE" -name kustomization.yaml -exec dirname {} \; | sort)

# ---------------------------------------------------------------------------
# 3. Deterministic archive
# ---------------------------------------------------------------------------
WORK="$SPIKE_ROOT/.local/tmp/package.$$"
mkdir -p "$WORK"
trap 'rm -rf "$WORK"' EXIT

ARCHIVE_NAME="manifests.tar.gz"

# Every flag below removes a source of nondeterminism:
#   --sort=name          directory order must not leak into the archive
#   --mtime=@EPOCH       timestamps come from the commit, not from the clock
#   --owner/--group/--numeric-owner  the building user must not matter
#   --mode=go+u,go-w     normalise permissions
#   --format=posix + pax-option  drop atime/ctime, which change on every read
#   gzip -n              no filename or timestamp in the gzip header
"$GTAR" --sort=name \
        --mtime="@${SOURCE_DATE_EPOCH}" \
        --owner=0 --group=0 --numeric-owner \
        --mode=go+u,go-w \
        --exclude=.DS_Store \
        --format=posix \
        --pax-option=exthdr.name=%d/PaxHeaders/%f,delete=atime,delete=ctime \
        -C "$SOURCE" -cf - . \
  | gzip -n -9 > "$WORK/$ARCHIVE_NAME"

LAYER_DIGEST="sha256:$(shasum -a 256 "$WORK/$ARCHIVE_NAME" | cut -d' ' -f1)"
LAYER_SIZE="$(wc -c < "$WORK/$ARCHIVE_NAME" | tr -d ' ')"

ok167::info "archive $ARCHIVE_NAME size=$LAYER_SIZE layer=$LAYER_DIGEST"

if [ "$DRY_RUN" -eq 1 ]; then
  printf 'LAYER_DIGEST=%s\n' "$LAYER_DIGEST"
  ok167::ok "dry run: nothing pushed"
  exit 0
fi

# ---------------------------------------------------------------------------
# 4. Authenticate
# ---------------------------------------------------------------------------
ok167::require_file "$CA" "CA certificate (run 'make pki')"
ok167::require_file "$CREDS" "credentials (run 'make identities')"
# shellcheck disable=SC1090,SC1091
. "$CREDS"

PASSWORD_VAR="OK167_$(printf '%s' "$IDENTITY" | tr 'a-z-' 'A-Z_')_PASSWORD"
eval "PASSWORD=\${$PASSWORD_VAR:-}"
[ -n "$PASSWORD" ] || ok167::die "no password for $IDENTITY in .local/credentials.env" 3

mkdir -p "$(dirname "$AUTH")"
# --password-stdin, never -p: a password on the command line is visible in the
# process list. --registry-config keeps the token out of ~/.docker.
if ! printf '%s' "$PASSWORD" | "$ORAS" login "$REGISTRY" \
      --username "$IDENTITY" --password-stdin \
      --ca-file "$CA" --registry-config "$AUTH" >/dev/null 2>&1; then
  ok167::die "could not authenticate to $REGISTRY as $IDENTITY" 3
fi
unset PASSWORD

# ---------------------------------------------------------------------------
# 5. Push
# ---------------------------------------------------------------------------
# oras rejects absolute paths and uses the given filename as the layer title,
# so the push runs from $WORK with a bare relative name. A path would otherwise
# end up inside the manifest and change the digest.
ANNOTATIONS=(
  "--annotation" "org.opencontainers.image.source=$SOURCE_URL"
  "--annotation" "org.opencontainers.image.revision=$GIT_SHA"
  "--annotation" "org.opencontainers.image.created=$CREATED"
  "--annotation" "org.opencontainers.image.version=$TAG"
  "--annotation" "org.opencontainers.image.title=$(basename "$SOURCE")"
  "--annotation" "org.opencontainers.image.description=OK-167 GitOps manifests packaged from $SOURCE"
)
if [ "$DIRTY" -eq 1 ]; then
  ANNOTATIONS+=("--annotation" "io.openkubes.source.dirty=true")
fi

ok167::info "pushing $REGISTRY/$REPOSITORY:$TAG"

PUSH_LOG="$WORK/push.json"
if ! ( cd "$WORK" && "$ORAS" push "$REGISTRY/$REPOSITORY:$TAG" \
         "$ARCHIVE_NAME:$LAYER_MEDIA_TYPE" \
         --artifact-type "$ARTIFACT_TYPE" \
         "${ANNOTATIONS[@]}" \
         --ca-file "$CA" \
         --registry-config "$AUTH" \
         --format json ) > "$PUSH_LOG" 2>"$WORK/push.err"; then
  ok167::error "push failed:"
  sed 's/^/    /' "$WORK/push.err" >&2
  exit 4
fi

MANIFEST_DIGEST="$("$JQ" -r '.digest // empty' "$PUSH_LOG" 2>/dev/null || true)"
if [ -z "$MANIFEST_DIGEST" ]; then
  MANIFEST_DIGEST="$(grep -oE 'sha256:[0-9a-f]{64}' "$PUSH_LOG" "$WORK/push.err" | head -1 | sed 's/.*sha256/sha256/')"
fi
[ -n "$MANIFEST_DIGEST" ] || ok167::die "push succeeded but no digest was reported" 4

# ---------------------------------------------------------------------------
# 6. Record
# ---------------------------------------------------------------------------
# Secrets never reach this file: it holds references and digests only.
EVIDENCE_DIR="$SPIKE_ROOT/evidence/raw"
mkdir -p "$EVIDENCE_DIR"
SAFE_REPO="$(printf '%s' "$REPOSITORY" | tr '/' '-')"
RECORD="$EVIDENCE_DIR/push-$SAFE_REPO-$TAG-$(date -u +%Y%m%dT%H%M%SZ).json"

# shellcheck disable=SC2016  # the $names below are jq variables, not shell ones
"$JQ" -n \
  --arg registry "$REGISTRY" \
  --arg repository "$REPOSITORY" \
  --arg tag "$TAG" \
  --arg manifest_digest "$MANIFEST_DIGEST" \
  --arg layer_digest "$LAYER_DIGEST" \
  --arg layer_size "$LAYER_SIZE" \
  --arg artifact_type "$ARTIFACT_TYPE" \
  --arg layer_media_type "$LAYER_MEDIA_TYPE" \
  --arg source "$SOURCE" \
  --arg git_sha "$GIT_SHA" \
  --arg source_date_epoch "$SOURCE_DATE_EPOCH" \
  --arg created "$CREATED" \
  --arg dirty "$DIRTY" \
  --arg pushed_at "$(ok167::timestamp)" \
  '{registry:$registry, repository:$repository, tag:$tag,
    manifest_digest:$manifest_digest, layer_digest:$layer_digest,
    layer_size:($layer_size|tonumber), artifact_type:$artifact_type,
    layer_media_type:$layer_media_type,
    provenance:{source:$source, git_revision:$git_sha,
                source_date_epoch:($source_date_epoch|tonumber),
                created:$created, dirty:($dirty=="1")},
    pushed_at:$pushed_at}' > "$RECORD"

printf 'DIGEST=%s\n' "$MANIFEST_DIGEST"
ok167::ok "pushed $REPOSITORY:$TAG -> $MANIFEST_DIGEST (record: ${RECORD#"$SPIKE_ROOT/"})"
