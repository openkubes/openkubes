# Developer Workspace Architecture & Contract

**OpenKubes owns workspace semantics, not the coding-agent implementation.**

The proposed [ADR-Platform-039](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-039-developer-workspace-contract.md) defines a `DeveloperWorkspace` as a declarative, bounded execution environment for a human, a coding agent, or both.

## Contract boundaries

| Boundary | Defined by the workspace contract |
| --- | --- |
| Source | Repository identity and requested source revision |
| Runtime | Replaceable profile such as OpenCode or another compatible agent |
| Inference | Explicit model service and connection capability, potentially supplied by OK AI |
| Storage | Ephemeral or persistent workspace filesystem and retention |
| Identity | Separate workspace identity, scoped credentials and workload ServiceAccount |
| Connectivity | Explicit Git, inference, registry and reviewed MCP/tool access |
| Resources | CPU, memory and storage constraints |
| Lifecycle & evidence | Create, run, idle, terminate, export required evidence and clean up |

```text
DeveloperWorkspace (candidate contract)
        |
        v
Reviewed implementation profile
        |
        +-- Namespace-based sandbox (first profile)
        |     +-- dedicated Namespace / ServiceAccount
        |     +-- scoped credentials and storage
        |     +-- ResourceQuota / LimitRange
        |     +-- default-deny NetworkPolicy + reviewed egress
        |
        +-- Future isolation profiles? (Kata / KubeVirt / remote)
        |
        v
Replaceable coding-agent runtime (OpenCode, Codex, ...)
        |
        v
Proposed changes + verification evidence
        |
        v
External human / organization approval and merge
```

## Isolation is explicit — but bounded

The Namespace reference profile restricts workspace resources and connectivity. It does **not** provide an independent VM kernel or a hostile multi-tenant isolation guarantee. Its security still depends on the cluster, nodes, CNI, storage implementation and reviewed runtime images.

The default Kubernetes capability is **no Kubernetes API authority**; broad kubeconfigs, cluster-admin access or ambient service-account credentials are outside the proposed default profile. Access to Git, inference and MCP endpoints is explicitly selected.

The live proof also identifies unresolved boundaries, including tool-level enforcement of declared MCP tools, incomplete storage capacity enforcement with local-path, and missing controller-owned reconciliation.

## Historical evidence and current health are different

An agent's completed and evidenced task must not be rewritten by later workspace drift. Current runtime health is separate from its historical terminal outcome — consistent with OpenKubes' evidence-first architecture.

Read the [proposed ADR](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-039-developer-workspace-contract.md) for the complete candidate invariants and non-goals.

[Back to Developer Workspace](index.md)
