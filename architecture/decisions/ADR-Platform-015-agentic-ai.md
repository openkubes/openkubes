# ADR-Platform-015: Agentic AI

**Status:** Proposed (pending Go/No-Go from OK-14 PoC)
**Date:** 2026-07-10
**Deciders:** Arash Kaffamanesh
**Reviewed:** Multi-model review (Arash / Claude / GPT / Gemini), 2026-07-10
**Related:** ADR-Platform-001 (Contracts, not Components), ADR-Platform-005 (Shared AI Services), ADR-Platform-011 (GitOps), OK-14, OK-15

---

## Context

OpenKubes already provides a shared AI services layer (ADR-Platform-005: Ollama on the infra cluster, Open WebUI provisioned via Crossplane as a self-service capability). What is missing is an **agentic** layer: an AI component that can not only answer questions, but call tools — inspect cluster state, query logs, trace Crossplane claims — and reason over the results.

An evaluation of OpenClaw produced two key findings:

1. **OpenClaw is not an enterprise-grade platform component.** It is a local, single-user AI assistant gateway (Node.js, MIT license): single process, no HA, no native multi-tenancy, community-supported. Adopting it *as a platform component* would violate the operational bar OpenKubes sets for owned components.

2. **OpenClaw is viable as an implementation profile behind a contract.** Combined with Open WebUI as the enterprise front layer (multi-user, OIDC via Keycloak, RBAC, Helm-deployed), OpenClaw can serve as an agent backend exposed through the Agent Interface Contract — appearing in Open WebUI simply as a selectable model. Open WebUI owns the enterprise concerns; OpenClaw provides tool execution and skill orchestration.

This maps directly onto the platform pattern from ADR-Platform-001:

| Layer | Instance |
|---|---|
| **Capability** | Agentic AI |
| **Contract** | Agent Interface Contract v1 + Skill Contracts (read-only) |
| **Implementation Profile** | Open WebUI (enterprise layer) + OpenClaw (agent backend) |
| **Provider Values** | LLM backend: Ollama (shared AI services, ADR-005) or KServe; skill implementations per instance |

The decisive consequence of this framing: **the capability is Agentic AI, not Kubernetes troubleshooting.** Troubleshooting is the first implementation case. Scoping the capability at the use-case level would couple the contract to a single scenario and force a new architectural decision for every subsequent agent.

## Decision

1. **OpenKubes adopts an Agentic AI capability.** The platform owns the contracts — the Agent Interface Contract and a set of read-only Skill Contracts — not the agent implementation.

2. **The Agent Interface Contract is versioned.**
   - **v1 = OpenAI Chat Completions API + Tool Calling.** This is the concrete, testable wire format the frontend layer speaks to the agent backend.
   - Future revisions (v2: MCP-native, A2A, Responses API, …) are handled as **contract evolution** — a documented version bump, not a new capability.
   - The platform capability remains unchanged while the contract version evolves.

3. **Skills are contracts, not tools.** Agents access the platform exclusively through named, read-only Skill Contracts; concrete tools are interchangeable implementations:

   | Skill Contract | Implementations (examples) |
   |---|---|
   | Cluster Inspection Contract | kubectl (read-only), kagent tool, MCP server |
   | Log Query Contract | OpenSearch client, MCP server |
   | Knowledge Graph Contract | okgraph query interface |
   | Documentation Contract | RAG over ADRs/guides (Open WebUI native) |

   Each agent instance declares its Skill Contracts explicitly (see OK-15, `spec.parameters.skills`); the declared set is the reviewed API surface of that agent.

   **Identity & Authorization:** Skill Contract implementations authenticate against downstream systems (Kubernetes API, OpenSearch) with the **agent pod's identity** — a per-instance Kubernetes ServiceAccount whose Role/RoleBinding is derived from the instance's declared Skill Contracts (read-only, Secrets excluded). Consequence: all users of a given agent instance share that instance's authorization scope; there is no per-user authorization at the skill layer. Open WebUI authenticates the *user*; the agent acts as its *ServiceAccount*. This is acceptable under the read-only default and is listed as an accepted risk. Per-user authorization (token forwarding / impersonation) is explicitly **deferred** — it would be a contract evolution consideration (v2), not an implementation detail.

   **Knowledge provisioning:** Platform-specific knowledge for skills (e.g. Talos/CAPI pitfalls for UC-2, network postmortem learnings for UC-4) is provided via **retrieval** (Documentation Contract: RAG over git-versioned docs/ADRs), never by fine-tuning the base LLM. Retrieval keeps operational knowledge versionable and git-bound — learnings change; a fine-tuned model does not forget. This mirrors the knowledge-graph principle: derived projections of Git, not primary stores.

4. **The initial implementation profile is the Open WebUI + OpenClaw tandem.** Open WebUI owns multi-user, authentication (OIDC/Keycloak), and RBAC. OpenClaw runs as a single-replica Kubernetes Deployment (`--bind lan`, token-authenticated gateway) and is registered in Open WebUI as a model. **State handling:** Open WebUI fully owns chat/conversation persistence (its database layer); the agent backend is treated as stateless and may lose all local state on pod restart — this justifies the single-replica Recreate deployment strategy (OK-15). Whether OpenClaw actually operates fully stateless is an assumption verified in the OK-14 PoC. OpenClaw is replaceable: any agent framework speaking Agent Interface Contract v1 can substitute it without touching the platform layer.

5. **Agents are read-only by default.** No agent receives write access to shared infrastructure. Diagnosis, explanation, report generation, and **drafting** of artifacts are in scope; applying, remediating, self-healing, and any mutation of cluster state are out of scope. This upholds the blast-radius principle and the governance manifesto: *AI may argue; only humans merge.* Any future write-capable agent requires its own ADR.

6. **Deployment follows the established two-phase pattern (OK-15).** Phase 1: Makefile + Helm for the PoC. Phase 2: Crossplane XRD (`OpenClawInstance`) for declarative self-service provisioning, consistent with the OpenWebUI XRD and the opt-in Makefile pattern.

## Architecture

```
                    User
                     │
                     ▼
               Open WebUI                 (enterprise layer:
                     │                     multi-user, OIDC, RBAC)
  ═══════════════════════════════════════
   Agent Interface Contract v1
   (OpenAI Chat Completions + Tool Calling)
  ═══════════════════════════════════════
                     │
               Agent Backend              (implementation profile:
          OpenClaw │ kagent │ ...          replaceable)
                     │
  ═══════════════════════════════════════
   Skill Contracts (read-only)
  ═══════════════════════════════════════
        │            │            │
   Cluster        Log Query    Knowledge
   Inspection                  Graph / Docs
        │            │            │
        ▼            ▼            ▼
   Kubernetes    OpenSearch    okgraph / ADRs
```

Double lines mark contract boundaries — everything between them is replaceable without a new ADR.

## Use Case Portfolio

The capability is intended to support the following use cases. Only UC-1 is in scope for the OK-14 PoC; the remainder validate that the contracts are cut wide enough. This ADR establishes a single architectural capability covering all nine use cases.

### Platform Operations (read-only diagnosis)

- **UC-1 — Kubernetes Troubleshooting Agent** *(PoC, OK-14)*: cluster health analysis, pod/deployment failure diagnosis, log analysis via the Log Query Contract, basic root cause analysis. Minimum three defined scenarios.
- **UC-2 — Storage Diagnosis Agent**: Longhorn volume health, degraded replicas, PVC binding issues — including known platform-specific pitfalls (e.g. `selected-node` annotation requirements for DataVolume/CDI scratch PVCs, ADR-Platform-009 context).
- **UC-3 — Cluster Lifecycle Assistant**: explain CAPI/Talos provisioning state ("why is my Machine stuck in Provisioning?"); trace Crossplane Claim → XR → Managed Resources for claim debugging.
- **UC-4 — Network Triage Agent**: Cilium/MetalLB/vSwitch diagnosis using codified operational learnings (stale ARP detection, overlay-vs-vSwitch path disambiguation) — postmortem knowledge as executable skills.

### Developer & User Self-Service

- **UC-5 — Provisioning Agent**: conversational self-service on top of platform XRDs — the agent **drafts** Crossplane Claims from natural-language requests and **proposes** them for review. The agent talks exclusively to platform contracts, never to components; a human applies the claim (the agent drafts, the human merges).
- **UC-6 — Onboarding & Documentation Agent**: answer questions against ADRs, deployment guides, and READMEs (Documentation Contract), with the agentic extension of verifying answers against live cluster state instead of quoting documentation alone.

### Governance & Engineering Workflow

- **UC-7 — Knowledge Graph Agent**: answer decision-history questions ("which ADR blocked RWX for VM boot disks, and which commits relate to it?") via the Knowledge Graph Contract. Reads decision history; makes no decisions.
- **UC-8 — Jira/Confluence Agent**: ticket summarization, ADR draft scaffolding from spike results, sprint hygiene — aligned with the planned MCP connector integration (MCP servers are one implementation class of Skill Contracts).
- **UC-9 — Drift & Compliance Reporter**: compare live cluster state against committed manifests and ADR constraints, report deviations (read-only precursor to full GitOps reconciliation, ADR-Platform-011 / OK-58).

## Out of Scope

- Write access to shared infrastructure: auto-remediation, self-healing, agent-initiated mutations of any kind (agents draft and propose; humans apply)
- Multi-tenant enterprise hardening of OpenClaw itself (Open WebUI owns this layer)
- HA for the agent backend (single process accepted for PoC; the contract is the exit strategy)
- GPU workloads, MLflow/Ray integration
- GDPR / EU AI Act compliance audit (deferred to a dedicated decision)

## Considered Alternatives (under evaluation)

- **kagent (Solo.io, CNCF Sandbox):** evaluated; architecturally compatible — Kubernetes-native, agents/tools/models as CRDs, structurally the closest match to the OpenKubes XRD pattern. Decision pending OK-14: the Go/No-Go recommendation evaluates OpenClaw explicitly against kagent (open questions tracked in OK-14).

## Rejected Alternatives

- **Epinio (MCP integration or as PaaS layer):** Evaluated as a potential agent-accessible application delivery layer. Rejected on three grounds: (1) Epinio is a competing abstraction that owns both contract and components (its own app model, buildpacks, CLI/API), bypassing the Capability → Contract → Implementation Profile chain; (2) the project is effectively dormant (verify current state before any re-evaluation); (3) the only meaningful agent use case — conversational app deployment — is write access to cluster infrastructure and thus outside this ADR by design. The underlying need (source-to-app developer experience) is real but belongs to a separate Application Delivery capability with its own ADR, for which Epinio would be at most one implementation profile among stronger candidates (Knative, kpack/Buildpacks, ArgoCD + templates).

## Consequences

**Positive:**
- The versioned Agent Interface Contract makes the agent backend swappable; no platform lock-in on a community project. Contract evolution (v2+) is a documented version bump, not an architectural rework.
- Open WebUI carries all enterprise concerns; OpenClaw's known limitations (single process, no multi-tenancy) are contained behind the contract.
- This single ADR covers all nine use cases; new agents are implementation work, not new architecture decisions — as long as they stay read-only and behind the contracts.
- Skill Contracts generalize beyond the agent layer: Cluster Inspection, Log Query, and Knowledge Graph interfaces are reusable platform abstractions.
- The read-only default keeps the agentic layer consistent with the governance manifesto and the blast-radius principle.

**Negative / Accepted Risks:**
- OpenClaw is a community project without enterprise support; the single-replica deployment is a deliberate PoC-grade compromise.
- Skill sprawl risk: each new Skill Contract widens the effective API surface an agent can reach. Mitigation: Skill Contracts are declared per instance (XRD `spec.parameters.skills`), reviewed like any other platform change.
- A read-only Cluster Inspection implementation still exposes cluster-internal information to the LLM path; Secrets access must be explicitly excluded from the implementation's RBAC.
- Shared instance identity: all users of an agent instance operate under that instance's ServiceAccount scope — no per-user authorization at the skill layer. Accepted under the read-only default; revisit if user-scoped access becomes a requirement (contract v2 consideration).

**Revisit triggers:**
- OK-14 PoC produces a No-Go → status moves to Rejected (documented outcome).
- kagent evaluation (OK-14) favors kagent as implementation profile → swap profile, contracts unchanged.
- A use case requires write access → new ADR required.
- Agent Interface Contract v1 becomes limiting (MCP-native, A2A) → contract version bump, documented as contract evolution.

## References

- OK-14 — PoC: OpenClaw + Open WebUI Tandem Architecture (incl. kagent evaluation questions)
- OK-15 — Deploy OpenClaw on OpenKubes: Makefile + Helm (Phase 1), Crossplane (Phase 2)
- ADR-Platform-001 — Contracts, not Components
- ADR-Platform-005 — Shared AI Services
- ADR-Platform-011 — GitOps
- OpenClaw GitHub: https://github.com/openclaw/openclaw
- Open WebUI OpenClaw integration: https://docs.openwebui.com/getting-started/quick-start/connect-an-agent/openclaw/
