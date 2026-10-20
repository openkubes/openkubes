# Developer Workspace — Validation & Roadmap

OpenKubes is actively validating a **contract-driven developer workspace** with OpenCode as its first coding-agent profile.

## Architecture direction and readiness — 20 October 2026

The architecture decision-holder recorded a **conditional GO to develop and test** against the proposed contract on 2026-10-19, clarified on 2026-10-20. This approves the architectural direction in principle. It does not establish implementation readiness. **ADR-Platform-039 remains Proposed, not Accepted.** See the [recorded conditional decision](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-039-conditional-acceptance-record.md).

All [nine mandatory readiness gates](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-039-readiness-gates.md) remain open before the Namespace profile can be called fully conforming:

1. Enforce connectivity permissions for each tool, beyond allowing its endpoint.
2. Enforce lifecycle timers and Review restrictions.
3. Export required evidence durably before cleanup; block cleanup if export fails.
4. Keep completed task outcomes unchanged when runtime health changes.
5. Deliver scoped credentials through the required Secret Contract.
6. Show full observable state: readiness, failure, termination, task outcomes and evidence.
7. Clean up automatically at the declared lifecycle limits, respecting storage retention.
8. Authorize creation, attachment, changes and deletion separately from the workspace's own identity.
9. Enforce a distinct Review profile with more restrictive tools and credentials than development. Local edits and declared tests remain allowed; merge authority does not follow. Any exception needs an explicit human architecture decision, a risk explanation and concrete security evidence. No exception is assumed approved.

Implementation owners for these gates still await confirmation. Recording the gates does not satisfy or waive them.

For persistent capacity, a configuration declaration is not proof. `runtimeEnforced: true` and its audit label are claims, not certification. Every advertised backend needs its own independent `persistent-capacity-enforced` runtime evidence under the required user-namespace boundary (`hostUsers: false`). The development/local-path profile is not capacity-conforming. Separate storage-fixture evidence does not extend the workspace proof.

**There is no production offering.** Full conformance and production readiness are not approved. Production use needs independently satisfied readiness gates and separate explicit approval. This decision adds no implementation or runtime evidence.

## Delivery status

| Public source / work area | Scope | Evidence and remaining work |
| --- | --- | --- |
| [Contract spike](https://github.com/openkubes/openkubes/tree/main/architecture/spikes/ADR-Platform-039) | Contract spike and OpenCode evaluation | Bounded proof recorded; ADR remains Proposed |
| [Namespace reference profile](https://github.com/openkubes/openkubes/tree/main/platform/workspace/developer-workspace/crossplane) | Namespace reference profile with OpenCode | Reconciler proven on disposable clusters; not production-ready |
| [Live isolation and lifecycle proof](https://github.com/openkubes/openkubes/blob/main/platform/workspace/developer-workspace/crossplane/README.md#live-proof-disposable-clusters-only) | Live isolation / lifecycle validation | Bounded disposable-cluster proof of resource bounds, drift correction and UID-bound cleanup recorded; restart/reboot persistence evidence is separate; limits described below |
| [Second coding-agent runtime proof](coding-agents.md#opencode-and-the-second-runtime-proof) | Second coding-agent runtime validation | OpenCode and Codex exercised under the same reviewed profile |
| [Capacity-enforcing workspace storage](https://github.com/openkubes/openkubes/blob/main/platform/workspace/developer-workspace/crossplane/README.md#hands-on-opencode-quickstart) | Reproducible capacity-enforcing workspace storage | Runtime capacity enforcement proven on disposable clusters with the ok-storage-local-quota XFS project-quota profile; cluster, storage and admission setup reproducible from repository entry points; not production-ready |
| [User / operator guide](https://github.com/openkubes/openkubes/blob/main/platform/workspace/developer-workspace/crossplane/README.md#hands-on-opencode-quickstart) | Operator guidance and OpenCode quickstart | Hands-on OpenCode quickstart (make live-up / live-down) available for disposable clusters; supported self-service installation remains future work |

*Describes the public repository state as of 18 October 2026.*

*Follow the public sources above for the proof scope and implementation guidance. This is a reference implementation, not production-ready; the table describes demonstrated behavior and remaining work rather than ticket status.*

For a guided first evaluation, see [Your First AI Coding Workspace](tutorial.md).

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
