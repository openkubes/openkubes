# OpenClaw + platform-diag — the Read-Only Platform Diagnostics CONSUMER.
#
# Same thin-derivative pattern as openclaw-kubectl, but the opposite intent:
# this image adds NO cluster tooling and NO credentials. It only ships the
# `platform-diag` CLI, which speaks the HTTP contract (the facade). OpenClaw's
# agent runs it via its Exec tool. Cluster access lives behind the contract
# (kagent's read-only SA), never in OpenClaw — ADR-021 authorization model.
#
# Build (multi-arch, like the facade):
#   docker buildx build --platform linux/amd64,linux/arm64 --provenance=false \
#     -t ghcr.io/openkubes/openclaw-diag:2026.7.1 --push .

ARG OPENCLAW_VERSION=2026.7.1
FROM ghcr.io/openclaw/openclaw:${OPENCLAW_VERSION}

# node is already on PATH in the base image (the CLI uses global fetch, Node 18+).
COPY --chmod=0755 platform-diag /usr/local/bin/platform-diag

# unchanged otherwise: same entrypoint, same non-root `node` user (uid 1000).
# The facade endpoint is injected at deploy time via env PLATFORM_DIAGNOSTICS_URL.
