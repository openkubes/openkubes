# OpenClaw consumer — `platform-diag` (ADR-021)

OpenClaw is the **first consumer** of the Read-Only Platform Diagnostics Contract.
It reaches diagnostics ONLY through the HTTP contract (the facade); it holds no
Kubernetes credentials (ADR-021 authorization model).

## Why a CLI, not MCP

Our OpenClaw deployment has **no MCP** wiring. Its shipped `openclaw.json` only has
`gateway`/`models`/`agents`, and the original "Cluster Inspection skill" was just
the **kubectl binary in the image** used through OpenClaw's built-in **Exec tool**
(we saw `Exec failed: kubectl get ns` from the agent after the RBAC handoff).

So the consistent, correct consumer is the same mechanism: a tiny `platform-diag`
CLI on PATH that calls the HTTP contract, invoked by the agent's Exec tool. This
keeps OpenClaw credential-less and is exactly what ADR-021 means by "OpenClaw is a
consumer, restricted to the contract, no cluster access." (The `ok` CLI, OK-76, is
another HTTP consumer of the same contract.)

```
Open WebUI → OpenClaw (agent) --Exec--> platform-diag --HTTP--> facade
             (no kube creds)                                     → kagent (read-only SA) → cluster
```

## The CLI

```
platform-diag health      [--clusters ok-ai,ok2]
platform-diag investigate --cluster ok-ai --namespace kube-system --workload coredns [--time-range PT1H]
platform-diag collect     --cluster ok-ai --namespace kube-system --workload coredns
```

Endpoint from env `PLATFORM_DIAGNOSTICS_URL` (default: the in-cluster facade svc).
Output is the raw ADR-021 JSON, for the agent to read and summarize.

## Deploy

Build the image (multi-arch) and point the OpenClaw release at it:

```bash
docker buildx build --platform linux/amd64,linux/arm64 --provenance=false \
  -t ghcr.io/openkubes/openclaw-diag:2026.7.1 --push .

# switch the openclaw release to this image + inject the facade endpoint,
# keep RBAC OFF (consumer holds no creds):
helm upgrade openclaw <openclaw-chart> -n openclaw --reuse-values \
  --set image.repository=ghcr.io/openkubes/openclaw-diag \
  --set rbac.create=false \
  --set-string extraEnv.PLATFORM_DIAGNOSTICS_URL=http://platform-diagnostics.platform-diagnostics.svc.cluster.local:8080
```

(If the openclaw chart has no `extraEnv`, set `PLATFORM_DIAGNOSTICS_URL` via
`kubectl -n openclaw set env deploy/openclaw ...`; the CLI also has a sane default.)

## Autonomous use — the one OpenClaw-config detail to confirm

The Exec tool lets the agent *run* `platform-diag`; to make it do so **on its own**
when a user asks a cluster question, the agent needs a system-prompt instruction
naming the CLI and when to use it. Our `openclaw.json` validates `agents.defaults`
**strictly** (only schema-supported keys), so the exact prompt field must be
confirmed against OpenClaw's config schema before adding it — do not guess the key.

Until then, the path is verifiable immediately by asking the agent in chat to run
it, e.g. *"run `platform-diag investigate --cluster ok-ai --namespace kube-system
--workload coredns` and summarize"* — the Exec tool executes it through the
contract, and the facade log confirms the call arrived via the contract (not via
any OpenClaw cluster access, which no longer exists).
