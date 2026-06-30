# ADR-Platform-004: Runner-based orchestration is an implementation detail, not the platform contract

**Date:** 2026-07-01  
**Status:** Accepted  
**Deciders:** Arash Kaffamanesh, GPT and Claude architectural review  
**Related:** ADR-Platform-001, ADR-Platform-002, ADR-Platform-003

---

## Context

`capi-platform-v4.2`'s Composition triggers a Kubernetes Job running a specific container image (`kubernautslabs/capi-platform-runner:v4.2`) that performs the actual CAPI/CAPK rendering and `kubectl apply` work. This runner is a genuinely useful pattern — it lets a Crossplane Composition (which cannot run arbitrary imperative logic well) delegate to a purpose-built container that can.

The open question: where does the *runner itself* — as opposed to the contract it fulfils or the Composition that invokes it — belong in the OpenKubes repository structure?

## Decision

> The runner container (image, Dockerfile, entrypoint, and the scripts it executes) is an implementation detail of how the Cluster Lifecycle contract gets fulfilled inside a Kubernetes-native, self-service execution path. It is not itself the contract, and it does not belong in `openkubes/openkubes`. It is treated as a "Platform Execution Environment" — a way of running `ok-cluster`-equivalent logic in-cluster rather than from an operator's terminal.

## Rationale

- **Two interfaces, one contract.** `ok-cluster` exposes the Cluster Lifecycle contract via a CLI/Makefile, executed locally by an operator. `capi-platform-v4.2`'s runner exposes conceptually the same contract via a Kubernetes Job, triggered by a Crossplane Claim. Both are legitimate interfaces to the same underlying responsibility — they should not be maintained as two independent implementations of the same logic.
- **The runner is a delivery mechanism, not a product.** Its job is to package whatever cluster-lifecycle logic exists (today: its own scripts; in the future: `ok-cluster` itself) into something a Kubernetes Job can execute non-interactively. This is analogous to how a CI runner packages build logic — the CI runner is not the build system.
- **Co-locating the runner with the contract creates the monolith risk ADR-Platform-002 warns about.** If `openkubes/openkubes` owns both the XRD/Composition (the contract) and the runner's internal CAPI-rendering logic (the implementation), every future bugfix to cluster-lifecycle behaviour requires touching the distribution repository — exactly the coupling OpenKubes is trying to avoid.
- **A converged future is visible from here.** The cleanest long-term shape: the Composition's Job runs a container that wraps `ok-cluster`'s own CLI (`make render && make install`, or equivalent), instead of maintaining a separate set of templates and scripts. The runner becomes a thin execution wrapper around `ok-cluster`, not a parallel implementation.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Keep the runner and its scripts inside openkubes/openkubes permanently | Violates ADR-Platform-002 (distribution layer should not own deep implementation logic) |
| Delete the runner, force all cluster creation through the ok-cluster CLI only | Removes the self-service / GitOps-friendly Kubernetes-API path that the XRD enables — a real, valuable capability |
| Build a brand-new "ok-runner" repository from scratch, ignoring capi-platform-v4.2's scripts | Discards already-hardened operational logic (race conditions, cleanup ordering) for no reason — contradicts ADR-Platform-003 |

## Consequences

**Positive:**
- Frees `openkubes/openkubes` to stay focused on contracts and integration (per ADR-Platform-002)
- Creates a clear target state: the runner eventually becomes a thin wrapper invoking `ok-cluster`, eliminating duplicate cluster-lifecycle logic
- Preserves the self-service / Kubernetes-API delivery path as a first-class, intentional feature rather than an accidental side effect of where code happened to live

**Negative / trade-offs:**
- Until the runner is refactored to wrap `ok-cluster`, two implementations of overlapping logic continue to exist temporarily
- Introduces an open question this ADR does not resolve: does the runner get its own repository (`ok-runner`?), or does it live inside `ok-cluster` as an optional in-cluster execution mode? This requires a follow-up decision.

**Neutral:**
- The runner's Dockerfile, entrypoint, and operationally-hardened scripts remain fully readable in `openkubes/openkubes/platform/cluster-management/capi-platform-v4.2/` until migration — same archival approach as ok-linux's `archive/` (ADR-007)

## Open follow-up — resolved

GPT's review (2026-07-01) recommends resolving this in favour of option 2: **`ok-cluster` becomes the shared backend executor for both the CLI interface and the Crossplane self-service interface.** No new `ok-runner` repository.

Target state:

```
Today:
  Crossplane Claim → Composition → capi-platform-runner:v4.2 (own templates/scripts)

Target:
  Crossplane Claim → Composition → container wrapping ok-cluster CLI
                                    (make render && make install, executed in-cluster)
```

This is evolutionary, not a deprecation: `capi-platform-v4.2` is not deleted, its responsibility migrates underneath `ok-cluster` step by step. The Composition's contract (the XRD) does not change — only what it invokes changes.

**Prerequisite before this migration starts:** `ok-cluster`'s CLI surface must reach parity with what the runner already does reliably (notably: the upgrade race-condition handling in `crossplane-upgrade.sh`, and clean Job-based execution semantics). Until then, `capi-platform-v4.2`'s runner remains the production path for Crossplane-triggered clusters, and `ok-cluster` remains the CLI path for locally-operated clusters — both honouring the same underlying Cluster Lifecycle Contract.
