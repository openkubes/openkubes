# ADR-Platform-003: capi-platform-v4.2 is the historical Platform Orchestrator prototype

**Date:** 2026-07-01  
**Status:** Accepted  

---

## Context

`capi-platform-v4.2` was built before the OpenKubes platform-layer vocabulary (ok-cluster, ok-linux, contracts vs components) existed. On first encounter, the natural question was whether it represents legacy code to be deprecated, or something else.

Applying the archaeology method (problem → continuity → contract) instead of a deprecation lens reveals: `capi-platform-v4.2` solved a real, still-existing problem — providing a self-service, Kubernetes-native API for cluster lifecycle operations — using mechanisms that, in hindsight, map cleanly onto the platform-layer model documented in `ok-linux`'s ADR-001 through ADR-008.

Specifically, it already implements:
- A declarative contract (`KubeVirtClusterClaim` XRD) — see ADR-Platform-001
- An integration layer (Composition routing the claim to a Job) — see ADR-Platform-002
- An execution environment (runner container) — see ADR-Platform-004
- Cluster lifecycle operations (deploy, upgrade, recreate, delete, status) — overlapping with `ok-cluster`
- Operationally-hardened logic (bootstrap token race conditions, ghost-node cleanup, ordered ingress cleanup) earned through real production use (50+ clusters claimed in README)

## Decision

> `capi-platform-v4.2` is recognised as the first Platform Orchestrator prototype within OpenKubes — not legacy code to be deleted, but a body of work to be re-homed according to the contracts it already implicitly satisfies.

## Rationale

- **The problems it solved still exist.** Self-service cluster provisioning via a Kubernetes API, ingress/TLS automation, cluster-manager UI deployment, rolling upgrades with race-condition handling — every one of these is still an open, valuable problem for OpenKubes.
- **Architecture archaeology is a sign of maturity, not stagnation.** Re-reading old code with the question "what problem did this solve, and does it still exist" — rather than "is this code old" — is how mature platforms avoid losing institutional knowledge embedded in working code.
- **Good abstractions explain the past.** ADR-Platform-001's claim ("OpenKubes owns the contracts, not the components") is validated precisely because it can explain why `capi-platform-v4.2` looked the way it did, years before that sentence was written.
- **Hardened operational logic is rare and valuable.** The upgrade script's handling of bootstrap-token race conditions and ghost-node cleanup represents real production lessons. Rewriting this from scratch in `ok-cluster` without consulting it would be a waste of already-paid "tuition."

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Deprecate capi-platform-v4.2 outright, build everything fresh in ok-cluster | Throws away hardened operational logic (race condition fixes, cleanup ordering) for no benefit |
| Keep capi-platform-v4.2 unchanged as a parallel system to ok-cluster | Creates exactly the duplicate-implementation problem this archaeology session exists to resolve |
| Treat capi-platform-v4.2 purely as documentation/inspiration, copy ideas manually | Loses traceability; future maintainers cannot see where a given piece of hardened logic actually originated |

## Consequences

**Positive:**
- No operational knowledge is lost — every script and Make target gets a deliberate new home rather than being silently dropped
- Future "is this dead code" questions about other prototypes can use the same method (problem / continuity / contract)
- `capi-platform-v4.2`'s README and Make-target catalogue become a checklist for what `ok-cluster` needs to eventually support (ingress, TLS, manager, upgrade-with-race-condition-fixes)

**Negative / trade-offs:**
- Re-homing is not a one-time refactor — it touches multiple repos (`ok-cluster`, possibly a new "Platform Execution Environment" repo per ADR-Platform-004) and will take several sessions
- Until the migration is complete, `capi-platform-v4.2` and `ok-cluster` continue to overlap in responsibility — this ADR does not resolve that immediately, only frames how to resolve it

**Neutral:**
- `capi-platform-v4.2`'s source remains in `openkubes/openkubes/platform/cluster-management/` as the historical reference during migration, analogous to `ok-linux`'s `archive/` directory (see ok-linux ADR-007)
