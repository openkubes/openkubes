# Developer Workspace — AI-Assisted Development on Kubernetes

**A bounded workspace for developers and coding agents. Contracts over runtimes.**

OpenKubes Developer Workspace is an emerging platform capability for running AI-assisted coding workflows in a controlled Kubernetes environment. **OpenCode** is the first reference coding-agent runtime; **Codex** has also been exercised against the same candidate contract.

The goal is a portable **DeveloperWorkspace** abstraction that defines source, execution, identity, connectivity, resources, lifecycle and evidence — without making a particular coding-agent product or Kubernetes Namespace part of the permanent platform API.

!!! info "Implementation status"
    **Reference proof available; platform work in progress.** [ADR-Platform-039](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-039-developer-workspace-contract.md) is **Proposed**, not Accepted. The bounded live proof reports 18/18 required effects for the reviewed Namespace profile, but there is **no production reconciling workspace controller or general self-service offering yet**.

## Explore Developer Workspace

| Topic | What it covers |
| --- | --- |
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
- [OK-175 — OpenCode reference profile](https://kubernauts.atlassian.net/browse/OK-175)
- [OK-176 — live isolation and lifecycle proof](https://kubernauts.atlassian.net/browse/OK-176)

**Security note:** The website intentionally does not link directly to raw runtime transcripts or cluster-specific operational evidence. They may contain environmental details and require independent review before redistribution.
