# OpenCode & Coding Agents

**OpenCode is the reference runtime — not the platform contract.**

The first Developer Workspace profile uses [OpenCode](https://opencode.ai/) as an AI coding agent running within a reviewed Kubernetes Namespace-based execution boundary.

## What the workspace provides

- A source checkout associated with a declared repository and revision.
- A replaceable coding-agent runtime, with the workspace filesystem and constrained compute resources.
- An explicitly selected inference service, rather than unrestricted access to every model endpoint on the network.
- Scoped Git, network and tool/MCP capabilities.
- A declared verification command, with independent checking of the agent's reported result.
- Evidence export and controlled cleanup for ephemeral workspaces.

These are **candidate contract semantics under validation**, not guarantees of a generally available hosted coding workspace.

## OpenCode and the second-runtime proof

The [ADR-Platform-039 live-proof package](https://github.com/openkubes/openkubes/tree/main/architecture/spikes/ADR-Platform-039/live) documents a bounded trial in which **OpenCode and Codex** ran against the same reviewed workspace profile with a declared source fixture and verification steps.

Both runtimes were exercised under the proof's explicit constraints, supporting runtime replaceability as an architectural direction. This does **not** prove that every coding agent, model or workload is supported.

## Relationship to OK AI

[OK AI](../ai/index.md) can provide model-serving and agent-related infrastructure. Developer Workspace is different: it controls the **coding execution environment**, source access, filesystem, credentials and lifecycle.

A coding workspace may consume an approved inference endpoint as a capability. It must never gain infrastructure authority merely because that endpoint or the workspace runs inside OpenKubes.

## Current scope

There is no turnkey workflow for production use. For evaluation on a **disposable** cluster, the reference implementation provides `make live-up` and `make live-down`, which bring one OpenCode workspace up and remove exactly what they created. Broader access control (a requester role) and production lifecycle operations remain implementation work.

See the [validation status](status.md) before evaluating the proof for your own environment.

[Back to Developer Workspace](index.md)
