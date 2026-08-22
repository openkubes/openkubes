containerfile = File.read(File.join(__dir__, "Containerfile"))
workflow = File.read(File.join(__dir__, "../../../.github/workflows/publish-console-observed-state-producer.yaml"))

abort("producer base image must be pinned by digest") unless containerfile.match?(%r{^FROM --platform=\$\{TARGETPLATFORM\} python:3\.13-alpine@sha256:[a-f0-9]{64}$})
abort("producer source label is required") unless containerfile.include?('org.opencontainers.image.source="https://github.com/openkubes/openkubes"')
abort("producer revision label is required") unless containerfile.include?('org.opencontainers.image.revision="${VCS_REF}"')
abort("producer must remain non-root") unless containerfile.include?("USER 65532:65532")

abort("publication must use only the bounded tag trigger") unless workflow.include?("tags:\n      - 'console-observer-dev-v*'")
abort("publication must not run for pull requests") if workflow.match?(/^\s*pull_request:/)
abort("publication must not be manually dispatched") if workflow.match?(/^\s*workflow_dispatch:/)
%w[contents:\ read packages:\ write id-token:\ write attestations:\ write].each do |permission|
  abort("missing permission #{permission}") unless workflow.include?(permission.tr("\\", ""))
end
abort("candidate revision must be reachable from main") unless workflow.include?('git merge-base --is-ancestor "${GITHUB_SHA}" origin/main')
abort("publication image name is wrong") unless workflow.include?("IMAGE_NAME: ghcr.io/openkubes/observed-state-producer")
abort("publication must cover amd64 and arm64") unless workflow.include?("platforms: linux/amd64,linux/arm64")
abort("published tag overwrite must fail closed") unless workflow.include?('docker buildx imagetools inspect "${IMAGE_NAME}:${GITHUB_REF_NAME}"')
abort("SPDX SBOM is required") unless workflow.include?("format: spdx-json") && workflow.include?("actions/attest-sbom@")
abort("build provenance is required") unless workflow.include?("actions/attest-build-provenance@")
abort("HIGH/CRITICAL scan is required") unless workflow.include?("severity: CRITICAL,HIGH")
abort("keyless signing and verification are required") unless workflow.include?("cosign sign --yes") && workflow.include?("cosign verify")

workflow.scan(/^\s*uses:\s+([^\s#]+)/).flatten.each do |action|
  abort("workflow action is not pinned: #{action}") unless action.match?(/@[a-f0-9]{40}$/)
end

abort("workflow must not reference a long-lived registry credential") if workflow.match?(/DOCKER_PASSWORD|REGISTRY_PASSWORD|COSIGN_PRIVATE_KEY/)
