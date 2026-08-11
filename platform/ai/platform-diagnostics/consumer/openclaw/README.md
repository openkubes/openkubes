# OpenClaw consumer via MCP (OK-94)

OpenClaw is the first conversational consumer of the Read-Only Platform
Diagnostics Contract. It uses only the thin MCP adapter and holds no Kubernetes
credentials:

```text
Open WebUI -> OpenClaw -> platform-diagnostics MCP adapter -> HTTP contract
                                                               -> provider
```

The OpenClaw chart owns the concrete consumer wiring:

- the `platform-diagnostics` MCP server points to the adapter, never directly to
  kagent or the facade;
- the tool filter exposes exactly `get_platform_health`,
  `investigate_workload`, and `collect_diagnostic_evidence`;
- the Exec tool is denied;
- the upstream OpenClaw image replaces the former kubectl derivative;
- ServiceAccount token automount is disabled on both the ServiceAccount and Pod;
- no Role, ClusterRole, or binding is rendered for the consumer; and
- the agent instructions preserve provenance and allow sanitized handoff to
  separately configured Jira, GitHub, or documentation tools.

The removed `platform-diag` CLI/Exec path was an early implementation scaffold.
It bypassed the MCP adapter required by ADR-021 and must not be reintroduced.

## Verify

```bash
cd platform/ai/openclaw
make verify-mcp-consumer
```

After deploying chart 0.2.0, run `make verify-mcp-live` to confirm the pod has no
ServiceAccount token or kubectl binary and that OpenClaw reports the restricted
MCP registration.
