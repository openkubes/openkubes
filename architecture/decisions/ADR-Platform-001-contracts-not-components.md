# ADR-Platform-001: OpenKubes owns the contracts, not the components

**Date:** 2026-07-01  
**Status:** Accepted  

---

## Context

Over several days of building `ok-linux` and `ok-cluster`, a pattern emerged independently in both repositories: each repository defines what it needs from its neighbours through a stable interface (a YAML field, a Makefile target, an XRD schema) — not through shared implementation code.

When the team performed an archaeological review of `capi-platform-v4.2` (an earlier prototype built with Crossplane, CAPI, and a runner container), the same pattern was found to already exist, just unnamed: a Crossplane `KubeVirtClusterClaim` XRD exposes fields like `provider`, `country`, `cni`, `controlPlane`, `workers` — a declarative contract that a Composition then fulfils through whatever mechanism is appropriate (today: a runner container; potentially in the future: `ok-cluster` directly).

This is analogous to how Kubernetes itself is structured: Kubernetes does not own `containerd`, `Calico`, or `Ceph`. It owns the CRI, CNI, and CSI contracts. Implementations are swappable; contracts are stable.

## Decision

> OpenKubes owns the contracts, not the components. Implementations (Talos, Cluster API, Crossplane, Argo CD, KubeVirt, or any future replacement) are interchangeable as long as they honour the platform's contracts.

## Rationale

- **Contracts outlive implementations.** `capi-platform-v4.2`'s `KubeVirtClusterClaim` schema has already outlived one full implementation cycle — the underlying runner could be replaced by `ok-cluster` without changing the contract a single consumer depends on.
- **This explains both the past and the future.** A good abstraction should explain existing code, not just describe future plans. This principle explains why `ok-linux` exists (it owns the OS contract, Talos is the implementation), why `ok-cluster` exists (it owns the cluster lifecycle contract, CAPI/CAPK is the implementation), and why `capi-platform-v4.2` was not a wrong turn — it was an early, unnamed instance of the same principle.
- **It prevents premature component-building.** Before OpenKubes builds a new component, the question is never "which tool should we use" first — it is "what contract does this need to satisfy, and does an existing contract already cover it."
- **It mirrors a proven pattern.** Kubernetes won not because it shipped the best container runtime, but because it defined CRI/CNI/CSI and let an ecosystem build implementations. OpenKubes applies the same idea one layer up: platform layers (Host OS, Cluster Lifecycle, Infrastructure, GitOps, Applications) are the contracts; Talos, CAPI, Crossplane, Argo CD are implementations.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| OpenKubes owns reference implementations for every layer | Leads to a monolith; couples platform identity to specific tool choices that may need to change |
| No explicit contracts — each repo does what makes sense locally | Already shown to create accidental duplication (capi-platform-v4.2 vs ok-cluster solving the same problem independently) |

## Consequences

**Positive:**
- New components are evaluated against "what contract does this fulfil" before any code is written
- Existing prototypes (like `capi-platform-v4.2`) are not deprecated outright — they are re-read as early contract implementations
- The architecture explains its own history, which is a strong signal that the abstraction is correct

**Negative / trade-offs:**
- Defining a contract well, upfront, takes more discipline than just writing an implementation
- Some existing code will need to be re-homed once its true contract is identified (see ADR-Platform-003, ADR-Platform-004)

**Neutral:**
- This ADR does not by itself specify what the contracts are — see the platform layer table in `openkubes/openkubes` architecture docs (to be formalised)
