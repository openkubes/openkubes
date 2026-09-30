#!/usr/bin/env bash
set -Eeuo pipefail
if [[ ${1:-} == checkout ]]; then
  shift
  exec /usr/local/bin/checkout "$@"
fi
: "${OK174_INFERENCE_BASE_URL:?runtime profile must provide OK174_INFERENCE_BASE_URL}"
: "${OK174_MODEL:?runtime profile must provide OK174_MODEL}"
config_dir=${XDG_CONFIG_HOME:-/home/workspace/.config}/opencode
mkdir -p "$config_dir"
printf '%s\n' "{\"model\":\"ok174/${OK174_MODEL}\",\"provider\":{\"ok174\":{\"npm\":\"@ai-sdk/openai-compatible\",\"name\":\"profile inference\",\"options\":{\"baseURL\":\"${OK174_INFERENCE_BASE_URL}\"},\"models\":{\"${OK174_MODEL}\":{\"name\":\"${OK174_MODEL}\"}}}}}" >"$config_dir/opencode.json"
if [[ $# == 0 ]]; then exec sleep infinity; fi
exec "$@"
