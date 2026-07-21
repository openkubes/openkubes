# OpenClaw + kubectl — thin derivative of the official image.
# kubectl is the Phase-1 implementation of the Cluster Inspection Contract
# (read-only; RBAC lives in the chart, NOT here). OK-15 Phase 1.
#
# Build via `make image-build` (pins versions, sets platform).

ARG OPENCLAW_VERSION=2026.7.1

# -- fetch stage: base image is node:24-bookworm-slim without curl -----------
FROM curlimages/curl:8.9.1 AS fetch
ARG KUBECTL_VERSION=v1.34.1
ARG TARGETARCH=amd64
RUN curl -fsSLo /tmp/kubectl \
      "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${TARGETARCH}/kubectl" \
 && curl -fsSLo /tmp/kubectl.sha256 \
      "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${TARGETARCH}/kubectl.sha256" \
 && echo "$(cat /tmp/kubectl.sha256)  /tmp/kubectl" | sha256sum -c -

# -- final image --------------------------------------------------------------
FROM ghcr.io/openclaw/openclaw:${OPENCLAW_VERSION}
COPY --from=fetch --chmod=0755 /tmp/kubectl /usr/local/bin/kubectl
# unchanged otherwise: same entrypoint, same non-root `node` user (uid 1000).
# In-cluster, kubectl authenticates via the pod ServiceAccount automatically.
