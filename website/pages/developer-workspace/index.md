# Developer Workspace — AI-Assisted Development on Kubernetes

**A bounded workspace for developers and coding agents. Contracts over runtimes.**

OpenKubes Developer Workspace is an emerging platform capability for running AI-assisted coding workflows in a controlled Kubernetes environment. **OpenCode** is the first reference coding-agent runtime; **Codex** has also been exercised against the same candidate contract.

The goal is a portable **DeveloperWorkspace** abstraction that defines source, execution, identity, connectivity, resources, lifecycle and evidence — without making a particular coding-agent product or Kubernetes Namespace part of the permanent platform API.

!!! info "Implementation status"
    **Reference implementation available; not production.** [ADR-Platform-039](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-039-developer-workspace-contract.md) is **Accepted** as the architectural contract; its nine readiness gates remain open. The contract spike reports 18/18 required effects for the reviewed Namespace profile, and a Crossplane reconciler for that profile has been proven on disposable clusters. There is **no production offering and no self-service creation**: only platform operators create workspaces.

## Explore Developer Workspace

| Topic | What it covers |
| --- | --- |
| [Your First AI Coding Workspace](tutorial.md) | A guided first evaluation of a bounded coding workspace |
| [Architecture & Contract](architecture.md) | Portable workspace semantics, isolation and authorization boundaries |
| [OpenCode & Coding Agents](coding-agents.md) | OpenCode reference runtime, second-runtime validation and inference |
| [Validation & Roadmap](status.md) | What the live proof demonstrates, known limits and delivery status |

## The development workflow

1. Declare a workspace's source repository and revision, runtime profile, model/inference choice and approved capabilities.
2. Render a restricted implementation profile (currently one Namespace per workspace).
3. Run an approved coding agent inside the workspace to inspect, edit and test source.
4. Export test outcomes, patches or other declared evidence before ephemeral cleanup.
5. Keep **review, merge, release and infrastructure transition authority outside the workspace**.

This is a reference workflow, **not yet an automated production deployment flow**.

## Source of truth

- [ADR-Platform-039 — Developer Workspace Contract (Proposed)](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-039-developer-workspace-contract.md)
- [Public workspace contract spike](https://github.com/openkubes/openkubes/tree/main/architecture/spikes/ADR-Platform-039)
- [OpenCode Namespace reference profile](https://github.com/openkubes/openkubes/blob/main/platform/workspace/developer-workspace/crossplane/README.md#hands-on-opencode-quickstart)
- [Live isolation and lifecycle proof](https://github.com/openkubes/openkubes/blob/main/platform/workspace/developer-workspace/crossplane/README.md#live-proof-disposable-clusters-only)
- [Reference implementation (Crossplane capability)](https://github.com/openkubes/openkubes/tree/main/platform/workspace/developer-workspace/crossplane)

**Security note:** The website intentionally does not link directly to raw runtime transcripts or cluster-specific operational evidence. They may contain environmental details and require independent review before redistribution.
