# ADR-Platform-002: openkubes/openkubes is the Platform Distribution and Integration Layer

**Date:** 2026-07-01  
**Status:** Accepted  

---

## Context

`openkubes/openkubes` began as what looked like a documentation repository — README, architecture diagrams, a reference architecture doc. Over time it accumulated real implementation: a Crossplane XRD, a Composition, and an entire `capi-platform-v4.2` runner with templates, scripts, and a Dockerfile.

This created ambiguity: is `openkubes/openkubes` documentation, or is it where OpenKubes actually runs?

The archaeology session revealed that the repository already contains the seed of the right answer — the Crossplane XRD/Composition pair is exactly the kind of artifact a "platform distribution" should own: a declarative contract (the XRD) plus the wiring that makes the contract operable (the Composition). What should not live here is the deep implementation logic behind that wiring (the runner container's CAPI rendering, upgrade race-condition handling, etc.) — that belongs in a dedicated implementation repository (see ADR-Platform-004).

## Decision

> `openkubes/openkubes` is the Platform Distribution and Integration Layer. It owns: the reference architecture, platform-wide contracts (XRDs, the future `Platform` CRD), Compositions that wire contracts to implementations, ADRs for platform-wide decisions, and end-to-end examples. It does not own deep implementation logic for any single platform layer.

## Rationale

- **A distribution assembles; it does not reimplement.** Just as a Linux distribution (Ubuntu, Fedora) packages and integrates upstream software without forking the kernel, `openkubes/openkubes` packages and integrates `ok-cluster`, `ok-linux`, `ok-gitops`, and `ok-apps` without reimplementing their internals.
- **The XRD is the right level of ownership.** `KubeVirtClusterClaim`'s schema (`provider`, `country`, `cni`, `controlPlane`, `workers`) is a platform-wide contract — exactly the kind of artifact that belongs in the distribution layer, because it is what every consumer (UI, GitOps, CLI) ultimately targets.
- **The Composition is integration, not implementation.** A Composition's job is to route a contract to whatever currently fulfils it. Today it might trigger a runner container; tomorrow it might call `ok-cluster` directly. The Composition belongs in the distribution layer because it is the integration glue, not the cluster-lifecycle logic itself.
- **This avoids the "monolith" failure mode.** If every subsystem's implementation logic accumulates inside `openkubes/openkubes`, the repository becomes exactly what GPT warned about: a place where "ach, das legen wir schnell hier rein" becomes the default, eroding the contract boundaries this entire archaeology session exists to establish.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| openkubes/openkubes is pure documentation, no code at all | Too restrictive — the platform genuinely needs a place to define and wire contracts; pure docs cannot do that |
| openkubes/openkubes owns full implementations of every layer | This is the monolith failure mode; duplicates what ok-cluster, ok-linux etc. already do better |
| Each ok-* repo defines its own XRD independently | Loses the cross-repo contract visibility that makes "OpenKubes owns the contracts" meaningful at the platform level |

## Consequences

**Positive:**
- Clear test for any new file: "is this a contract/integration artifact, or is it deep implementation logic for one layer?" — the second case migrates out
- `capi-platform-v4.2`'s XRD and Composition stay; its runner's internal scripts become a candidate for migration (see ADR-Platform-003, ADR-Platform-004)
- Future platform-wide ADRs (like this one) have an obvious home: `openkubes/openkubes/architecture/decisions/`

**Negative / trade-offs:**
- Requires ongoing discipline — it is always tempting to add "just this one implementation detail" directly to the distribution repo
- Some refactoring debt is created immediately: capi-platform-v4.2's runner scripts need a new home

**Neutral:**
- This ADR does not mandate an immediate migration — see ADR-Platform-003 for how to treat existing code during the transition
