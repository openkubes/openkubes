#!/usr/bin/env bash
set -Eeuo pipefail
if [[ ${1:-} == checkout ]]; then
  shift
  exec /usr/local/bin/checkout "$@"
fi
: "${OK174_INFERENCE_BASE_URL:?runtime profile must provide OK174_INFERENCE_BASE_URL}"
: "${OK174_MODEL:?runtime profile must provide OK174_MODEL}"
mkdir -p /home/workspace/.codex
cat > /home/workspace/.codex/config.toml <<EOF
model_provider = "ok174"
model = "${OK174_MODEL}"

[model_providers.ok174]
name = "profile inference"
base_url = "${OK174_INFERENCE_BASE_URL}"
wire_api = "responses"
EOF
if [[ $# == 0 ]]; then exec sleep infinity; fi
exec "$@"
