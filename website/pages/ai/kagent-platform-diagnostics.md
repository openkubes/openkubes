# kagent & Platform Diagnostics

**Read-only Kubernetes diagnostics behind a provider-neutral contract.**

OpenKubes integrates [kagent](https://github.com/kagent-dev/kagent) as **Provider Profile A** for the [Read-Only Platform Diagnostics Contract (ADR-Platform-021)](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-021-read-only-platform-diagnostics-contract.md). This is a *diagnostics provider*, not another chat model exposed alongside OpenClaw in Open WebUI.

## How the components fit together

```text
Open WebUI (chat frontend)
        |
        v
OpenClaw (conversational consumer)
        |
        v
MCP adapter -> Platform Diagnostics Contract (HTTP + OpenAPI)
                  |
                  v
           kagent facade (Profile A)
                  |
                  v
         openkubes-platform-agent
                  |
                  +-- Kubernetes specialist
                  +-- Cilium specialist
                  +-- Observability specialist
                  +-- Helm / Argo specialists (declared)
                  |
                  v
         Scoped read-only Kubernetes tools
```

The facade maps the public contract operations into kagent invocations and shapes results back into the contract schema. Internal agent delegation stays invisible to the consumer. A **deterministic stub (Profile B)** exercises backend substitution without changing the external contract.

## Three public diagnostic operations

| Contract operation | Purpose |
| --- | --- |
| `get_platform_health` | Summarize the observed health of platform resources |
| `investigate_workload` | Investigate a specified workload through bounded diagnostics |
| `collect_diagnostic_evidence` | Return diagnostic evidence references suitable for independent assessment |

These operations are specified by the [machine-readable OpenAPI contract](https://github.com/openkubes/openkubes/blob/main/platform/ai/platform-diagnostics/contract/openapi.yaml). The contract — not the kagent implementation — defines inputs, outputs, capability limits and error semantics.

## Security and authorization

- Consumers such as OpenClaw do **not** receive Kubernetes credentials.
- The kagent provider profile uses a dedicated ServiceAccount and a **scoped tools server**. The approved Kubernetes verbs are read-only (`get`, `list`, `watch`), and **Secrets are excluded**.
- A prompt asking for a write is not an authorization. Tool selection alone is insufficient: read-only enforcement must occur at the Kubernetes RBAC boundary.
- Remediation proposals and **execution of approved remediation** are separate phases. Executing changes requires additional architectural authorization and is **not** part of the read-only diagnostics contract.

## Implementation status and boundaries

The repository contains the provider profile, facade, contract tests and provider-neutral stub. This page does **not** claim that every specialist is live or that a production-ready operations agent can modify the cluster.

The [kagent profile README](https://github.com/openkubes/openkubes/blob/main/platform/ai/platform-diagnostics/profiles/kagent/README.md) documents a deployment-time prerequisite for the scoped tools server: its image, arguments, port and transport must be resolved from the installed kagent deployment. Until it is configured and enabled, the specialist agents that depend on its RemoteMCPServer can remain unaccepted. Consult the source-owned runbooks and live evidence before claiming deployment readiness.

Separate standalone kagent trials in [`ok-cluster`](https://github.com/openkubes/ok-cluster/tree/main/ok-kagent/kagent) are evaluation work and must not be confused with the read-only Profile A contract.

## Source documentation

- [Platform Diagnostics overview](https://github.com/openkubes/openkubes/blob/main/platform/ai/platform-diagnostics/README.md)
- [kagent Provider Profile A](https://github.com/openkubes/openkubes/blob/main/platform/ai/platform-diagnostics/profiles/kagent/README.md)
- [ADR-Platform-021: Read-Only Platform Diagnostics](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-021-read-only-platform-diagnostics-contract.md)
- [ADR-Platform-015: Agentic AI](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-015-agentic-ai.md)
- [OpenClaw consumer](openclaw.md)
- [Agentic Operations reference](agentic-operations.md)

[Back to OK AI](index.md)
