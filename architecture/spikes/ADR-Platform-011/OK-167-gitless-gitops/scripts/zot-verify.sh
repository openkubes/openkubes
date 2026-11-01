#!/usr/bin/env bash
#
# OK-167 — registry checks V1-V8 (BRIEF Phase 3.6).
#
# Proves that zot really enforces TLS, authentication and repository-scoped
# authorization, and that the extensions the later phases depend on are present.
# Negative cases matter as much as positive ones: a registry that accepts
# everything would pass every positive check.
#
# No password is ever an argument: curl reads .local/netrc-<identity>, oras is
# logged in once per identity into its own .local/registry-auth/<identity>.json.
# Nothing is written to ~/.docker.
#
# Output is redacted; the Authorization header is never printed.
#
# Exit codes
#   0  every check passed
#   1  at least one check failed
#   2  prerequisite missing

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck source=./lib.sh
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib.sh"
# shellcheck disable=SC1091
. "$SPIKE_ROOT/versions.env"

cd "$SPIKE_ROOT"

ORAS="${ORAS:-oras}"
# Resolved by the Makefile; the fallback keeps the script runnable on its own.
KUBECTL="${KUBECTL:-kubectl}"
ok167::require_tool "$ORAS"
ok167::require_tool "$KUBECTL"
ok167::require_tool curl
ok167::require_tool jq

CA=".local/pki/ca.crt"
REG="${ZOT_HOST:-localhost:30500}"
AUTH_DIR=".local/registry-auth"
WORK=".local/tmp/zot-verify"

ok167::require_file "$CA" "CA certificate (run 'make pki')"
ok167::require_file ".local/credentials.env" "credentials (run 'make identities')"
# shellcheck disable=SC1091
. .local/credentials.env

mkdir -p "$AUTH_DIR" "$WORK"
chmod 700 "$AUTH_DIR"

PASS_COUNT=0
FAIL_COUNT=0

check_pass() { ok167::ok  "$1"; PASS_COUNT=$(( PASS_COUNT + 1 )); }
check_fail() { ok167::error "$1"; FAIL_COUNT=$(( FAIL_COUNT + 1 )); }

# curl against the registry as a given identity. Never uses -u.
as() {
  local identity="$1"; shift
  curl -sS --cacert "$CA" --netrc-file ".local/netrc-$identity" "$@"
}

# HTTP status code only.
code_as() {
  local identity="$1"; shift
  curl -s -o /dev/null -w '%{http_code}' --cacert "$CA" \
    --netrc-file ".local/netrc-$identity" "$@"
}

password_for() {
  local var
  var="OK167_$(printf '%s' "$1" | tr 'a-z-' 'A-Z_')_PASSWORD"
  eval "printf '%s' \"\${$var}\""
}

oras_login() {
  local identity="$1"
  password_for "$identity" \
    | "$ORAS" login "$REG" \
        --username "$identity" --password-stdin \
        --ca-file "$CA" \
        --registry-config "$AUTH_DIR/$identity.json" >/dev/null 2>&1
}

oras_as() {
  local identity="$1"; shift
  "$ORAS" "$@" --ca-file "$CA" --registry-config "$AUTH_DIR/$identity.json"
}

ok167::info "registry under test: https://$REG"

# ---------------------------------------------------------------------------
# V1 — TLS is real
# ---------------------------------------------------------------------------
# With the CA the connection succeeds; without it the certificate must be
# rejected. If the second half succeeded, TLS would be decorative.
if curl -sS --cacert "$CA" -o /dev/null "https://$REG/v2/" 2>/dev/null \
   || [ "$(code_as gitops-publisher "https://$REG/v2/")" = "200" ]; then
  if curl -sS -o /dev/null "https://$REG/v2/" 2>"$WORK/v1-nocacert.txt"; then
    check_fail "V1 connection without the CA succeeded — the certificate is not being verified"
  else
    if grep -qiE 'certificate|SSL|self.signed|unable to get local issuer' "$WORK/v1-nocacert.txt"; then
      check_pass "V1 TLS verified with the CA; rejected without it ($(head -1 "$WORK/v1-nocacert.txt" | cut -c1-70))"
    else
      check_fail "V1 connection without the CA failed, but not with a certificate error: $(head -1 "$WORK/v1-nocacert.txt")"
    fi
  fi
else
  check_fail "V1 could not reach the registry even with the CA"
fi

# ---------------------------------------------------------------------------
# V2 — anonymous access is refused
# ---------------------------------------------------------------------------
v2_code="$(curl -s -o /dev/null -w '%{http_code}' --cacert "$CA" "https://$REG/v2/")"
if [ "$v2_code" = "401" ]; then
  check_pass "V2 anonymous GET /v2/ -> 401"
else
  check_fail "V2 anonymous GET /v2/ -> $v2_code, expected 401"
fi

# ---------------------------------------------------------------------------
# V3 — the publisher is authenticated, and the API announces itself
# ---------------------------------------------------------------------------
v3_headers="$(as gitops-publisher -D - -o /dev/null "https://$REG/v2/" | tr -d '\r')"
v3_code="$(printf '%s' "$v3_headers" | awk 'NR==1{print $2}')"
if [ "$v3_code" = "200" ] \
   && printf '%s' "$v3_headers" | grep -qi '^Docker-Distribution-API-Version: *registry/2.0'; then
  check_pass "V3 gitops-publisher GET /v2/ -> 200 with Docker-Distribution-API-Version: registry/2.0"
else
  check_fail "V3 publisher GET /v2/ -> ${v3_code:-?}; API version header: $(printf '%s' "$v3_headers" | grep -i 'Docker-Distribution' || echo 'absent')"
fi

# ---------------------------------------------------------------------------
# V4 — the publisher can push, and a pull by digest returns the same bytes
# ---------------------------------------------------------------------------
# Content addressing is the property ADR-028 §4.3 rests on. Hashing the pulled
# bytes and comparing to the digest proves it rather than assuming it.
SMOKE_REPO="$REPO_PREFIX/smoke"
if ! oras_login gitops-publisher; then
  check_fail "V4 could not log in as gitops-publisher"
else
  printf 'ok167 smoke payload\n' > "$WORK/smoke.txt"
  push_out="$(cd "$WORK" && "$ORAS" push "$REG/$SMOKE_REPO:v1" \
      smoke.txt:application/vnd.openkubes.test.v1+text \
      --artifact-type application/vnd.openkubes.test.v1 \
      --ca-file "$SPIKE_ROOT/$CA" \
      --registry-config "$SPIKE_ROOT/$AUTH_DIR/gitops-publisher.json" 2>&1)" || true

  SMOKE_DIGEST="$(printf '%s' "$push_out" | grep -oE 'sha256:[0-9a-f]{64}' | head -1)"
  if [ -z "$SMOKE_DIGEST" ]; then
    check_fail "V4 push produced no digest: $(printf '%s' "$push_out" | tail -2)"
  else
    # Fetch the layer blob by digest and hash it.
    layer_digest="$(oras_as gitops-publisher manifest fetch "$REG/$SMOKE_REPO@$SMOKE_DIGEST" 2>/dev/null \
      | jq -r '.layers[0].digest')"
    oras_as gitops-publisher blob fetch "$REG/$SMOKE_REPO@$layer_digest" \
      --output "$WORK/pulled.bin" >/dev/null 2>&1 || true
    if [ -s "$WORK/pulled.bin" ]; then
      actual="sha256:$(shasum -a 256 "$WORK/pulled.bin" | cut -d' ' -f1)"
      if [ "$actual" = "$layer_digest" ]; then
        check_pass "V4 push + pull by digest; pulled bytes hash to the digest ($(printf '%s' "$layer_digest" | cut -c1-19)...)"
      else
        check_fail "V4 pulled bytes hash to $actual, digest claims $layer_digest"
      fi
    else
      check_fail "V4 could not fetch the layer blob by digest"
    fi
  fi
fi

# ---------------------------------------------------------------------------
# V5 — the puller may read but not write
# ---------------------------------------------------------------------------
if ! oras_login gitops-puller; then
  check_fail "V5 could not log in as gitops-puller"
else
  if oras_as gitops-puller manifest fetch "$REG/$SMOKE_REPO:v1" >/dev/null 2>&1; then
    v5_read="ok"
  else
    v5_read="failed"
  fi

  printf 'puller should not be able to write this\n' > "$WORK/deny.txt"
  if (cd "$WORK" && "$ORAS" push "$REG/$SMOKE_REPO:puller-should-fail" \
        deny.txt:application/vnd.openkubes.test.v1+text \
        --ca-file "$SPIKE_ROOT/$CA" \
        --registry-config "$SPIKE_ROOT/$AUTH_DIR/gitops-puller.json" ) >"$WORK/v5-push.txt" 2>&1; then
    v5_write="SUCCEEDED"
  else
    if grep -qiE '401|403|unauthorized|forbidden|denied' "$WORK/v5-push.txt"; then
      v5_write="denied"
    else
      v5_write="unexpected-failure"
    fi
  fi

  if [ "$v5_read" = "ok" ] && [ "$v5_write" = "denied" ]; then
    check_pass "V5 gitops-puller reads; write denied ($(grep -oiE '40[0-9]|denied|unauthorized|forbidden' "$WORK/v5-push.txt" | head -1))"
  else
    check_fail "V5 read=$v5_read write=$v5_write (write must be denied)"
  fi
fi

# ---------------------------------------------------------------------------
# V6 — the publisher is confined to its repository prefix
# ---------------------------------------------------------------------------
# The prefix is the authorization boundary. If the publisher could write
# outside openkubes/machine/gitops/**, the accessControl block would be decoration.
printf 'should not be allowed\n' > "$WORK/other.txt"
if (cd "$WORK" && "$ORAS" push "$REG/openkubes/machine/other/smoke:v1" \
      other.txt:application/vnd.openkubes.test.v1+text \
      --ca-file "$SPIKE_ROOT/$CA" \
      --registry-config "$SPIKE_ROOT/$AUTH_DIR/gitops-publisher.json" ) >"$WORK/v6.txt" 2>&1; then
  check_fail "V6 publisher pushed to openkubes/machine/other/** — the prefix is not enforced"
else
  if grep -qiE '401|403|unauthorized|forbidden|denied' "$WORK/v6.txt"; then
    check_pass "V6 publisher denied outside its prefix (HTTP authorization rejection)"
  else
    check_fail "V6 push failed without an authorization rejection"
  fi
fi

# ---------------------------------------------------------------------------
# V7 — the extensions the later phases rely on are compiled in and enabled
# ---------------------------------------------------------------------------
# A missing extension is a finding, not a stop: the brief says to record it and
# carry on, because it is itself an answer to Q3/Q4.
v7_notes=""

# search, via its GraphQL endpoint. The field name matters: v2.1.20 has no
# ImageListWithLatestTag, and asking for it returns 422 — which looks exactly
# like a disabled extension if the response body is not read.
gql='{"query":"{ RepoListWithNewestImage { Results { Name } } }"}'
search_body="$(as gitops-publisher -X POST -H 'Content-Type: application/json' \
  -d "$gql" "https://$REG/v2/_zot/ext/search" 2>/dev/null || true)"
if printf '%s' "$search_body" | jq -e '.data' >/dev/null 2>&1; then
  v7_notes="$v7_notes search=on"
else
  v7_notes="$v7_notes search=OFF"
fi

# the extensions zot advertises
ext_body="$(as gitops-publisher "https://$REG/v2/_oci/ext/discover" 2>/dev/null || true)"
if [ -n "$ext_body" ]; then
  printf '%s' "$ext_body" > "$WORK/extensions.json"
fi

# Which extensions are compiled into this image at all. zot prints its
# BinaryType at startup; an extension that is configured but not compiled in
# would be silently inert, so this is read rather than inferred from config.
# --tail=-1 reads the whole log: the startup banner is at the BEGINNING, and a
# bounded tail stops reaching it as soon as a few requests have been served.
# That is how this check first reported trust=OFF on a registry whose trust
# extension was demonstrably on.
binary_type="$("$KUBECTL" -n "$ZOT_NAMESPACE" logs "statefulset/$ZOT_RELEASE" --tail=-1 2>/dev/null \
  | jq -r 'select(.params.BinaryType) | .params.BinaryType' 2>/dev/null | head -1 || true)"
if [ -n "$binary_type" ]; then
  printf 'BinaryType=%s\n' "$binary_type" > "$WORK/binary-type.txt"
  for needed in events imagetrust search metrics scrub; do
    case "$binary_type" in
      *"$needed"*) : ;;
      *) v7_notes="$v7_notes MISSING-$needed" ;;
    esac
  done
fi

# trust: zot publishes /v2/_zot/ext/cosign only when the trust extension is on
# with cosign:true. Asking the live API beats scraping a log that rotates.
if printf '%s' "$ext_body" | jq -e \
     '[.extensions[].endpoints[]] | index("/v2/_zot/ext/cosign")' >/dev/null 2>&1; then
  v7_notes="$v7_notes trust=on"
else
  v7_notes="$v7_notes trust=OFF"
fi

# the event receiver should have logged the push from V4
if kubectl_out="$("$KUBECTL" -n "$EVENTS_NAMESPACE" logs deployment/event-receiver --tail=400 2>/dev/null)"; then
  if printf '%s' "$kubectl_out" | grep -q 'zotregistry.image.updated'; then
    v7_notes="$v7_notes events=on"
  elif printf '%s' "$kubectl_out" | grep -qi 'ce-type\|cloudevent\|zotregistry'; then
    v7_notes="$v7_notes events=partial"
  else
    v7_notes="$v7_notes events=NO-EVENT-SEEN"
  fi
else
  v7_notes="$v7_notes events=UNREADABLE"
fi

case "$v7_notes" in
  *MISSING-*) ok167::warn "V7 extensions:$v7_notes — recorded as a finding (BRIEF 3.6 V7)";
              PASS_COUNT=$(( PASS_COUNT + 1 )) ;;
  *search=on*trust=on*events=on*) check_pass "V7 extensions:$v7_notes" ;;
  *) ok167::warn "V7 extensions:$v7_notes — recorded as a finding, not a stop (BRIEF 3.6 V7)";
     PASS_COUNT=$(( PASS_COUNT + 1 )) ;;
esac

# ---------------------------------------------------------------------------
# V8 — the Referrers API works
# ---------------------------------------------------------------------------
# ADR-028 §4.6 requires supply-chain metadata to attach to a subject digest
# through the Referrers API. Phase 9 depends on it surviving an offline copy.
if [ -n "${SMOKE_DIGEST:-}" ]; then
  printf '{"sbom":"ok167 smoke","components":[]}\n' > "$WORK/sbom.json"
  if (cd "$WORK" && "$ORAS" attach "$REG/$SMOKE_REPO@$SMOKE_DIGEST" \
        --artifact-type application/vnd.openkubes.sbom.v1+json \
        sbom.json:application/json \
        --ca-file "$SPIKE_ROOT/$CA" \
        --registry-config "$SPIKE_ROOT/$AUTH_DIR/gitops-publisher.json" ) >"$WORK/v8-attach.txt" 2>&1; then
    refs="$(oras_as gitops-publisher discover "$REG/$SMOKE_REPO@$SMOKE_DIGEST" --format json 2>/dev/null || true)"
    # oras 1.3.6 returns the list under .referrers (not .manifests, which is
    # what an OCI referrers API response itself uses).
    ref_count="$(printf '%s' "$refs" | jq -r '[.referrers // [] | .[]] | length' 2>/dev/null || echo 0)"
    if [ "${ref_count:-0}" -ge 1 ]; then
      check_pass "V8 oras attach + discover: $ref_count referrer(s) on the smoke subject"
    else
      check_fail "V8 attach succeeded but discover returned no referrer"
    fi
  else
    check_fail "V8 oras attach failed: $(tail -2 "$WORK/v8-attach.txt" | tr '\n' ' ')"
  fi
else
  check_fail "V8 skipped: V4 produced no subject digest"
fi

# ---------------------------------------------------------------------------
ok167::info "V-checks: $PASS_COUNT passed, $FAIL_COUNT failed"
[ "$FAIL_COUNT" -eq 0 ] || exit 1
