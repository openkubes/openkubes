# Developer Workspace — Validation & Roadmap

OpenKubes is actively validating a **contract-driven developer workspace** with OpenCode as its first coding-agent profile.

## Delivery status

| Work item | Scope | Recorded status |
| --- | --- | --- |
| [OK-174](https://kubernauts.atlassian.net/browse/OK-174) | Contract spike and OpenCode evaluation | Done |
| [OK-175](https://kubernauts.atlassian.net/browse/OK-175) | Namespace reference profile with OpenCode | In Progress |
| [OK-176](https://kubernauts.atlassian.net/browse/OK-176) | Live isolation / lifecycle validation | In Progress |
| [OK-177](https://kubernauts.atlassian.net/browse/OK-177) | Second coding-agent runtime validation | Done |
| [OK-185](https://kubernauts.atlassian.net/browse/OK-185) | Reproducible capacity-enforcing workspace storage | In Progress |
| [OK-180](https://kubernauts.atlassian.net/browse/OK-180) | User / operator guide and OpenCode quickstart | In Progress |

*Statuses reflect the project snapshot on 14 October 2026; follow the linked tickets for subsequent changes.*

## What has been proven

The current [candidate verdict](https://github.com/openkubes/openkubes/blob/main/architecture/spikes/ADR-Platform-039/developer-workspace-verdict-v1.yaml) recommends **GO** for continued work and records a bounded live proof covering 18/18 required effects for OpenCode and Codex under a reviewed Namespace implementation profile.

The proof demonstrates declared command execution and independently checked fixture verification, selected network restrictions, ServiceAccount token controls, resource and storage behaviors, credential checks and UID-scoped cleanup. Negative controls were used to ensure failed preconditions produced failures.

The Crossplane reference implementation was then proven on disposable Talos clusters: reconciliation and drift correction, refusal of duplicate workspace identities, the operator/non-operator authority boundary (including a full enumeration of who can steer the privileged provider), CPU, memory and runtime storage-capacity enforcement under user namespaces, admission policies that must be in place before any workspace is created, and UID-bound cleanup for the hands-on mode. A deliberately false capacity declaration was refused certification.

## What has not been proven

- **Not production operation:** the reconciler is proven on disposable clusters only; there is no requester role, upgrade path or production support yet.
- **Not hostile multi-tenant isolation:** the Namespace-based profile shares the underlying Kubernetes kernel and trusts its infrastructure.
- **Not exhaustive credential security:** scoped credential scans cannot disprove all data exfiltration.
- **Not tool-level MCP authorization:** tested reachability does not establish `approvedTools` enforcement inside the agent.
- **Not reproducible image build attestation:** captured image digests are not end-to-end attestations.
- **Not production authority:** agent execution never implies approval to merge, release or deploy.

The governing [ADR-Platform-039](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-039-developer-workspace-contract.md) remains **Proposed**. The live validation is meaningful engineering evidence, not a product GA announcement.

## Next steps

Complete the current implementation and validation tasks, resolve the remaining contract and security boundaries, review/accept the ADR through the project's human architecture process, and only then document a supported self-service installation flow.

[Back to Developer Workspace](index.md)
