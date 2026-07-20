# ADR-Platform-016: OS Capability Contract

**Status:** Accepted — three-way review completed (Arash / Claude / GPT, 2026-07-10)
**Date:** 2026-07-10
**Deciders:** Arash Kaffamanesh
**Related:** ADR-Platform-001 (Contracts, not Components), ADR-Platform-012 (Air-gapped Image Mirroring), ADR-Platform-014 (Constrained Edge Profile), ok-linux ADR-001 ff.

---

## Context

ADR-Platform-001 asserts that "ok-linux owns the OS contract, Talos is the implementation" — but the platform ADR series never formalized that contract. Every other load-bearing capability has its contract ADR: Storage (ADR-009), Ingress (ADR-010), GitOps (ADR-011), Cluster Registration (ADR-013), Agentic AI (ADR-015). The OS is the only capability whose contract exists by assertion, not by decision.

This was harmless while exactly one implementation profile existed (Talos on KubeVirt VMs, datacenter). ADR-Platform-014 changes that: the constrained edge profile is the **second consumer** of the OS capability, and its requirements (§1) already presuppose an OS contract ("immutable or declarative OS lifecycle", "A/B rollback", "ARM64 first-class") that is written down nowhere as a platform decision. As with cluster registration (ADR-013), the second consumer forces the formalization.

A second motivation: ADR-Platform-009 taught us that contract guarantees written for one constraint envelope silently break in another (`ok-storage-block` replication guarantee vs. single-node edge). The OS contract is therefore written envelope-aware from the start.

This ADR does not invent the contract. It records the one the architecture already explains. The need for it emerged only when a second implementation profile appeared, making previously implicit assumptions explicit.

## Decision

> **The Operating System is a platform capability. `ok-linux` owns its contract and all implementation profiles. No other ok-* repository decides OS versions, images, schematics, or lifecycle mechanics — they consume the contract.**

Following the established platform pattern:

### Capability

**Operating System** — the node OS lifecycle for every Kubernetes node in every OpenKubes cluster, across all constraint envelopes.

### Contract

Any OS implementation profile MUST provide:

| Guarantee | Applies in envelope |
|---|---|
| **Immutable, declarative, API-managed lifecycle** — no imperative, SSH-based node mutation; desired state is a versioned, machine-readable configuration | all |
| **Versioned image identity** — every node image is reproducibly identified by profile + version (today: `TALOS_SCHEMATIC_ID` + `TALOS_VERSION` from `profile.yaml`); consumers reference identity, never build images | all |
| **Transactional upgrade** — an OS upgrade either completes to the new version or leaves the node on the previous one; no partially-upgraded nodes | all |
| **Sovereign image distribution** — images are consumable from platform-owned storage; no external service required at cluster-creation time (per ADR-012) | all |
| **amd64 support** | datacenter |
| **ARM64 as first-class architecture** | constrained edge |
| **A/B rollback for unattended recovery** | constrained edge (datacenter recovery may rely on re-provisioning via CAPI) |

Consumers (`ok-cluster` templates, Crossplane Compositions, edge golden-image tooling) bind to the contract exclusively through the versioned image identity and, per ADR-012, the golden image published by `ok-linux`. No manifest in any ok-* repo may reference OS internals (installer URLs, extension lists, machineconfig fragments) directly.

### Implementation Profiles

| Envelope | Profile | Implementation | Status |
|---|---|---|---|
| Datacenter | `kubevirt`, `gpu`, ... | Talos (VM images, Image Factory build-time, golden PVC distribution per ADR-012) | Accepted (ok-linux ADR-001) |
| Constrained edge | `ok-edge-constrained` OS profile | Talos ARM64/SBC **or** minimal immutable OS + K3s — spike-gated | Open, decided by OK-64 spike, recorded in a follow-up ADR per ADR-014 |
| future | — | any OS honouring this contract | — |

This ADR deliberately does **not** select an operating system implementation. It defines the contract against which candidate implementations are evaluated; ADR-014 §2 owns the candidate matrix and evaluation criteria for the constrained edge envelope. Note the consequence for the spike: a candidate that cannot provide transactional upgrades at the OS layer fails the contract regardless of runtime merits.

### Provider Values

Per-profile, per-site variation is confined to Provider Values and never leaks into the contract:

- schematic / image extensions (e.g. iscsi-tools, gvisor, NVIDIA)
- kernel arguments
- machineconfig patches (network, registries)
- edge: site-specific config surface per ADR-014 §5 ("small config surface")

### Ownership rules

- `ok-linux` owns: the contract above, all OS profiles, image build **and** distribution (golden-image publish per ADR-012), and the per-envelope profile matrix.
- OS *implementation* decisions (extensions, Talos features, kernel parameters) are recorded as **ok-linux repo ADRs**, not platform ADRs. A platform ADR is required only when the contract itself changes.
- `ok-cluster` consumes `os.schematic_id` (existing integration contract) and remains ignorant of how images are built.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Keep the OS contract implicit (status quo) | Worked with one profile; ADR-014 already builds on unwritten guarantees — the edge spike would evaluate candidates against a contract that does not exist |
| Fold this into the planned Capability→Contract meta-ADR | The meta-ADR describes the *pattern*; this is a concrete *instance*. Mixing them makes the meta-ADR carry capability-specific tables it should not own |
| Platform ADR per OS implementation decision | Contradicts ADR-Platform-002 (distribution layer does not own deep implementation logic); ok-linux repo ADRs are the right home |

## Consequences

**Positive:**
- ADR-014's OS requirements now derive from a committed contract instead of assumptions; the OK-64 spike has an explicit conformance target, including a hard transactional-upgrade criterion.
- The ok-linux roadmap (Phases 2–3: edge schematics, golden-image publish) is contract-driven, not convention-driven.
- Envelope-scoped guarantees avoid a second ADR-009-style retroactive contract repair.

**Negative / cost:**
- ADR-009's `ok-storage-block` guarantee table must still be amended (or superseded by the Constraint Envelope ADR) — this ADR sets the precedent but does not fix storage retroactively (tracked separately).
- Two ADR layers (platform contract vs. ok-linux repo ADRs) require discipline about where a given decision belongs.

**Re-evaluation triggers:**
- OK-64 spike concludes → follow-up ADR records the edge OS selection under this contract.
- Constraint Envelope ADR is accepted → §"Contract" table may be restructured to reference envelopes formally (amendment, not rewrite).
- A third envelope appears (e.g. orbital, per ADR-014 non-goals) → extend the guarantee table; the contract itself is unchanged.

## References

- ADR-Platform-001, -002, -012, -014
- ok-linux ADR-001 (Talos as standard OS), ok-linux roadmap Phases 2–3
- OK-64 (edge OS spike)
