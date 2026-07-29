# OK-14 — OpenClaw + Open WebUI UC-1 evidence (2026-07-29)

This records the reproducible PoC evidence requested in OK-14. The run used
`ok-ai`, the `openclaw` model in Open WebUI, and the Profile A diagnostics
provider from OK-92.

## Deployed components

| Component | Observed version |
|---|---|
| OpenClaw | `2026.7.1` |
| platform-diagnostics facade | `ghcr.io/openkubes/platform-diagnostics-facade:0.1.3` |
| MCP adapter | `ghcr.io/openkubes/platform-diagnostics-mcp-adapter:0.1.0` |
| kagent tools server | `ghcr.io/kagent-dev/kagent/tools:0.2.1` |

All deployments were available on `ok-ai` during the run.

## Troubleshooting scenarios

The automated evidence runner was invoked with:

```console
platform/ai/openclaw/scripts/uc1-evidence.sh --skip-restart
```

It verified the contract shape, retrievable evidence references, capability
deltas, and the absence of embedded secret-like material.

| Scenario | Result | Evidence |
|---|---|---|
| Platform health | Explicitly unverified | The deployed `0.1.3` facade returned `status=unknown`. OK-92 changes the draft scaffold to return only `healthy`, `degraded`, or explicit `unavailable` with a reason. |
| ImagePullBackOff | Pass | `uc1-imagepull` reached `ImagePullBackOff`; the top hypothesis named the missing/non-existent image, all hypotheses had confidence and counter-evidence status, and every available evidence item had a retrievable URI. |
| CrashLoopBackOff | Explicitly unverified | `uc1-crashloop` reached `CrashLoopBackOff`. The provider response was rejected because hypotheses referenced labels instead of exact evidence URIs and one hypothesis did not check counter-evidence. OK-92 tightens the provider prompt and keeps unverified output explicit. |
| Capability delta | Pass | Events, logs, and describe evidence were available. `host_journal` was returned as `unavailable` with a reason; `node_shell=false` was also declared instead of silently omitted. |

The machine-readable run summary was `26 passed, 7 failed, 5 manual`. The
failures above were retained as honest boundary evidence and are owned by
OK-92; they did not result in fabricated diagnoses.

## Open WebUI and MCP provenance

The Open WebUI conversation was titled
`Workload Crash Loop Status — Open WebUI`. Before the restart, it exercised:

1. `platform-diagnostics/investigate_workload`
2. `platform-diagnostics/collect_diagnostic_evidence`
3. the capability-delta response for unavailable host diagnostics

The answers included these trailing provenance lines:

```text
Source: platform-diagnostics/investigate_workload
Source: platform-diagnostics/collect_diagnostic_evidence
```

The MCP adapter simultaneously recorded `ListToolsRequest`,
`CallToolRequest`, and successful HTTP 200 calls to:

```text
/v1/investigate_workload
/v1/collect_diagnostic_evidence
```

After the backend restart and an explicit MCP probe, a follow-up health request
completed through the same path and ended with:

```text
Source: platform-diagnostics/get_platform_health
```

The adapter recorded the corresponding `CallToolRequest` and HTTP 200 response
from `/v1/get_platform_health`.

## Statelessness and restart test

Before the test:

- pod: `openclaw-6bb9b94d8-d6l8k`
- started: `2026-07-28T12:08:55Z`
- restart count: `0`
- persistent volume claims: `0`

The exact pod was deleted and replaced by the Deployment. After the test:

- pod: `openclaw-6bb9b94d8-2nffl`
- started: `2026-07-29T11:53:31Z`
- restart count: `0`
- rollout: successful

The same Open WebUI conversation URL retained its title and all three complete
pre-restart user/assistant exchanges. A post-restart follow-up also completed
through the persisted MCP server definition. This passes the OK-14 criterion:
OpenClaw can be replaced without losing Open WebUI conversation state.

The MCP server definition remained present in the ConfigMap and in
`/home/node/.openclaw/openclaw.json`. `openclaw mcp doctor` returned `ok`, and
`openclaw mcp probe platform-diagnostics --json` returned all three expected
tools with no diagnostics.

## Security checks

The expanded Profile A RBAC verification passed on `ok-ai`:

- declared verbs are limited to `get`, `list`, and `watch`;
- Secrets and wildcard resources are absent from the ClusterRole;
- the expected ServiceAccount binding is present;
- `get`, `list`, and `watch` on pods are allowed;
- `get`, `list`, and `watch` on Secrets are denied;
- `create`, `update`, `patch`, `delete`, and `deletecollection` on pods are
  denied.

OpenClaw itself holds no cluster kubeconfig or cluster credential. Cluster reads
remain behind the diagnostics contract and its scoped ServiceAccount.
