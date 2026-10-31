#!/usr/bin/env bash
#
# OK-211 — X6: verify signatures and SLSA provenance of two Knative release
# images with cosign, as documented in "Verifying Knative Images"
# (keyless; identity signer@knative-releases.iam.gserviceaccount.com,
# issuer https://accounts.google.com). Read-only: nothing is signed or uploaded.
# The caller (make) exports TUF_ROOT into .local/.
#
# Usage: scripts/supply-chain.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
ok211::load_versions
ok211::require_tool cosign

RAW="$SPIKE_ROOT/evidence/raw"
M="$SPIKE_ROOT/.local/manifests/1.24/serving-core.yaml"
ID=signer@knative-releases.iam.gserviceaccount.com
ISS=https://accounts.google.com
out="$RAW/x6-cosign-$(ok211::stamp).txt"

img() { yq -N "select(.kind == \"Deployment\" and .metadata.name == \"$1\") | .spec.template.spec.containers[0].image" "$M"; }

{
  echo "# X6 $(ok211::timestamp) — $(cosign version 2>&1 | grep GitVersion)"
  echo "TUF_ROOT=${TUF_ROOT:-<unset>}"
  for d in controller activator; do
    i="$(img "$d")"
    echo; echo "## $d: $i"
    echo "### cosign verify --certificate-identity $ID --certificate-oidc-issuer $ISS"
    if cosign verify --certificate-identity "$ID" --certificate-oidc-issuer "$ISS" "$i" > "$SPIKE_ROOT/.local/x6-$d-verify.json" 2> "$SPIKE_ROOT/.local/x6-$d-verify.err"; then
      echo "result: VERIFIED"; grep -v '^$' "$SPIKE_ROOT/.local/x6-$d-verify.err" | sed 's/^/  /'
      jq -r '.[0] | "  subject: \(.optional.Subject // "-")  issuer: \(.optional.Issuer // "-")  docker-manifest-digest: \(.critical.image["docker-manifest-digest"])"' "$SPIKE_ROOT/.local/x6-$d-verify.json"
    else
      echo "result: FAILED"; sed 's/^/  /' "$SPIKE_ROOT/.local/x6-$d-verify.err" | tail -5
    fi
    echo "### cosign verify-attestation --type slsaprovenance02"
    if cosign verify-attestation --certificate-identity "$ID" --certificate-oidc-issuer "$ISS" --type slsaprovenance02 "$i" > "$SPIKE_ROOT/.local/x6-$d-att.json" 2> "$SPIKE_ROOT/.local/x6-$d-att.err"; then
      echo "result: VERIFIED"
      head -1 "$SPIKE_ROOT/.local/x6-$d-att.json" | jq -r '.payload' | base64 --decode | jq -c '{predicateType, builder: .predicate.builder.id, buildType: .predicate.buildType, subject: [.subject[] | .name]}'
    else
      echo "result: FAILED"; sed 's/^/  /' "$SPIKE_ROOT/.local/x6-$d-att.err" | tail -5
    fi
  done
} > "$out"
jq -cn --arg ts "$(ok211::timestamp)" --arg raw "${out#"$SPIKE_ROOT/"}" \
  --arg res "$(grep -E '^## |^### |^result' "$out" | tr '\n' '|')" \
  '{id: "X6", timestamp_utc: $ts, knative_version: "1.24.0", config: {identity: "signer@knative-releases.iam.gserviceaccount.com", issuer: "https://accounts.google.com"}, runs: [], stats: {summary: $res}, notes: "read-only verification against the public Sigstore infrastructure", raw: [$raw]}' >> "$RAW/measurements.json"
cat "$out"
