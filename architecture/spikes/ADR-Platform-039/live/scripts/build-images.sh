#!/usr/bin/env bash
set -Eeuo pipefail
: "${NODE_IMAGE:?}"
: "${IMAGE_REGISTRY:=ok174-build.invalid}"
[[ "$NODE_IMAGE" == 'node@sha256:36ae19f59c91f3303c7a648f07493fe14c4bd91320ac8d898416327bacf1bbfa' ]] || { echo 'NODE_IMAGE must equal the approved pinned Node digest' >&2; exit 2; }
docker build --build-arg "NODE_IMAGE=$NODE_IMAGE" -t "$IMAGE_REGISTRY/developer-workspace-opencode:1.18.33" runtime/opencode
docker build --build-arg "NODE_IMAGE=$NODE_IMAGE" -t "$IMAGE_REGISTRY/developer-workspace-codex:0.158.0" runtime/codex
docker build --build-arg "NODE_IMAGE=$NODE_IMAGE" -t "$IMAGE_REGISTRY/developer-workspace-fixture:1" fixtures
