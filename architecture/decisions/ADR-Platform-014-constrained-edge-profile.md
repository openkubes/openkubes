# ADR-Platform-014: Constrained Edge Implementation Profile

**Status:** Draft / Spike Required
**Date:** 2026-07-09
**Deciders:** Arash (pending three-way review: Arash / Claude / GPT)
**Related:** ADR-Platform-001 (Contracts over Components), ADR-Platform-011 (GitOps via ArgoCD), ADR-Platform-012 (Air-gapped Image Mirroring / Golden Images), ADR-Platform-013 (Workload Cluster Registration)

## Context

OpenKubes currently targets datacenter-class bare-metal infrastructure (host cluster on
dedicated servers, workload clusters as KubeVirt VMs). A growing class of use cases
requires Kubernetes on **constrained, remote, unattended hardware**:

- Satellite ground stations (antenna sites, often rural, intermittent backhaul)
- Wind turbines and renewable energy sites (nacelle/base controllers, SCADA-adjacent workloads)
- Industrial edge, retail, maritime (same constraint envelope)

Space-constrained environments (orbital compute payloads) are a long-term research
direction and not part of this implementation profile; the constraint envelope defined
here is deliberately a subset of theirs.

These environments share a constraint envelope fundamentally different from the datacenter:

1. **Hardware:** SBC-class devices (Raspberry Pi 4/5, CM4/CM5, industrial ARM boards),
   1–8 GB RAM, SD/eMMC/NVMe storage, no ECC, no IPMI/BMC.
2. **Connectivity:** intermittent, low-bandwidth, high-latency, possibly metered
   (LTE, satellite backhaul). Push-based management is not viable.
3. **Operations:** no on-site personnel. Physical access is expensive (crane, site visit).
   Devices must survive power loss, recover autonomously, and never require SSH-based rescue.
4. **Scale:** fleets of tens to hundreds of clusters, mostly single-node, provisioned
   from identical images with per-site variation limited to a small config surface.

Per ADR-Platform-001, OpenKubes owns **contracts, not components**. The question is not
"which distribution runs on a Pi" but "which Implementation Profile satisfies the existing
Capability Contracts under this constraint envelope."

> **Note (emerging concept):** This ADR uses *constraint envelope* informally to describe
> the operating conditions a profile must satisfy (datacenter, constrained edge, ...).
> Formalizing constraint envelopes as a first-class platform concept — sitting between
> Platform Principles and Implementation Profiles — is a candidate for a future ADR.

## Decision

We introduce a new Implementation Profile: **`ok-edge-constrained`**.

**Scope of this ADR:** ADR-014 does not decide the final edge stack. It introduces the
constrained edge profile and defines the invariants and requirements that any
implementation must satisfy. Component selection follows from the validation spikes
and will be recorded in follow-up ADRs.

### 1. Profile requirements

Any implementation of `ok-edge-constrained` MUST provide:

- **Immutable or declarative OS lifecycle** — no imperative, SSH-based node management;
  A/B rollback capability for unattended recovery.
- **ARM64 support** as a first-class architecture.
- **Single-node capable cluster runtime** without quorum requirements — no etcd
  consensus dependency across intermittent links.
- **Pull-based GitOps** — the edge agent initiates reconciliation; bandwidth-aware,
  offline-tolerant.
- **Offline-capable image strategy** — golden device images with preloaded workload
  images; delta sync over the link, never full pulls (extends ADR-012).
- **Single-node local storage** satisfying the `ok-storage-block` (RWO) contract.
  The `ok-storage-block` contract guarantees block storage semantics (RWO
  provisioning, lifecycle and scheduling integration). It intentionally does **not**
  guarantee replication or durability. Durability characteristics are profile-specific
  and, at the constrained edge, are compensated at the fleet level rather than the
  node level (see §5, *Redundancy lives in the fleet layer, not the node*).
- **Fleet registration** into ok-mgmt per ADR-Platform-013; edge-specific device
  identity and bootstrap hardening are a follow-up ADR.
- **Minimal telemetry** — the platform SHALL provide sufficient telemetry for the
  fleet layer to distinguish between *healthy*, *partitioned*, and *unreachable/dead*
  nodes without requiring physical site access. The telemetry mechanism itself is
  spike-gated (see Open Decisions); the requirement is not.

### 2. Candidate implementations (to be validated by spike)

| Requirement | Candidate implementations | Evaluation criteria |
|---|---|---|
| OS lifecycle | Talos ARM64 (Image Factory schematics, ok-linux Phase 2); minimal immutable OS + K3s as fallback | SBC hardware support maturity, A/B rollback, image size |
| Cluster runtime | K3s (SQLite datastore); Talos single-node | Memory footprint, datastore behavior under power loss |
| GitOps agent | Fleet; ArgoCD pull model | Bandwidth footprint, offline tolerance, scale to 100s of clusters |
| Image strategy | Preloaded image tarballs; embedded registry mirror (e.g. Spegel/Zot) | Delta-sync capability, storage overhead on SD/eMMC |
| Local storage | local-path-provisioner; openebs-local | RWO contract conformance, behavior on SD wear |
| Ingress | Traefik hostPort; klipper-lb | No L2-announcement dependency |

> Current implementation maturity differs between candidates (e.g. Talos SBC/ARM64
> support and Image Factory reliability vs. K3s ecosystem maturity) and will be
> evaluated empirically during the validation spike. This ADR intentionally makes
> no recommendation until spike results are available.

### 3. Capability → Contract mapping

| Capability | Contract (unchanged) | Datacenter Profile | Constrained Edge Profile |
|---|---|---|---|
| Cluster runtime | Conformant Kubernetes API | RKE2 / Talos (KubeVirt VM) | Single-node runtime per profile requirements |
| OS | Immutable, declarative, API-managed | Talos (VM images) | Immutable ARM64 OS per profile requirements |
| Storage | `ok-storage-block` (RWO) | Longhorn | Node-local RWO provisioner |
| Ingress | HTTP(S) entrypoint contract | MetalLB → Traefik | hostPort/klipper-class entrypoint, no L2 dependency |
| GitOps | Pull-based reconciliation | ArgoCD (ADR-011) | Pull agent, connectivity-window sync |
| Images | Air-gapped capable (ADR-012) | Golden images via CDI `source: pvc` | Golden device images + delta sync |
| Fleet management | Declarative cluster inventory | ok-mgmt (Crossplane/CAPI) | ok-mgmt registration per ADR-013 |

### 4. Provisioning model

- **Golden image first:** a site device is flashed (or factory-provisioned) with a
  versioned golden image produced by `ok-linux`. First boot: device registers with
  ok-mgmt over any available link, receives its site-specific config (Provider Values),
  reconciles to desired state. No imperative provisioning steps.
- `ok-linux` becomes the authoritative source for edge schematics, extending its
  existing role for `TALOS_SCHEMATIC_ID` (Phase 2/3 of the ok-linux roadmap).

### 5. Platform principles & operational invariants

> **Platform Principle:** Redundancy lives in the fleet layer, not the node.
> (Corollary of "redundancy lives on exactly one layer" — at the constrained edge,
> that layer is the fleet, never the single-node cluster.)

> **Platform Invariant:** Edge nodes are not managed because they are reachable.
> They are managed because they eventually reconcile.

- **Pull, never push.** The management plane never assumes reachability of an edge node.
- **Autonomy under partition.** A site cluster must run its workloads indefinitely
  without management-plane contact; reconciliation resumes on reconnect.
- **Unattended recovery.** Power-loss recovery, A/B image rollback, and watchdog-based
  self-healing must require zero human interaction.
- **Small config surface.** Per-site variation is restricted to Provider Values
  (site ID, network, workload selection). Everything else is the golden image.

### 6. Explicit non-goals (this ADR)

- Multi-node HA at a single site (single-node is the default; HA sites are a
  datacenter-profile problem).
- Replicated storage at the edge.
- Orbital deployment. Space-constrained environments are a long-term research direction
  and not part of this implementation profile. The profile is designed so that such an
  extension would change hardware and link parameters, not contracts.

## Consequences

**Positive:**
- Validates the contracts-over-components claim on a radically different substrate —
  strong narrative value (conference talks, positioning) and real market pull
  (industrial edge, energy, ground segment).
- Reuses ADR-011/012 investments directly; air-gapped patterns get a second consumer.
- ok-linux roadmap gains a concrete driver for Phases 2–3.

**Negative / cost:**
- ARM64 becomes a supported architecture → CI matrix, image builds, and testing effort roughly double for affected components.
- Fleet-scale management (100s of clusters) will surface ok-mgmt scaling questions
  (Crossplane provider load, secret sprawl) earlier than the datacenter roadmap would.
- New failure modes (SD card wear, brownouts, clock drift without NTP) need runbooks.

**Open decisions (spike-gated, each resolved in a follow-up ADR or amendment):**
1. GitOps agent selection (Fleet vs. ArgoCD pull model) at fleet scale.
2. OS/runtime selection: Talos ARM64/SBC maturity vs. K3s-on-minimal-OS — hardware
   test on a real Pi 5 / CM5 required.
3. Device identity & trust bootstrap (TPM? token-based? SPIFFE?).
4. Observability implementation under metered links (metrics downsampling,
   store-and-forward) — the *minimal telemetry* requirement itself is fixed in §1;
   only the mechanism is open.

## Validation plan

1. **Spike:** single Raspberry Pi 5, golden image, single-node cluster (candidate
   matrix from §2), pull-based sync against ok-mgmt — target: flash-to-workload
   without SSH.
2. **Mini-fleet:** 3–5 devices, simulated link interruptions (tc/netem), verify
   autonomy-under-partition invariant.
3. `make e2e-edge` target following the established opt-in Makefile pattern.
