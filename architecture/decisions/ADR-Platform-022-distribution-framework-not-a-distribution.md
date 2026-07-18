# ADR-Platform-022: OpenKubes is a distribution framework, not a distribution

**Date:** 2026-07-17
**Status:** Draft — pending Acceptance Condition (see below)
**Extends:** ADR-Platform-001
**Refines:** ADR-Platform-002

---

## Context

On 2026-07-16 the project repositioned its public claim:

> **"OpenKubes is a framework for building sovereign Kubernetes platform distributions."**

The README, the architecture diagram, the GitHub description, and the launch meetup were updated accordingly — before a decision record existed. Under the project's own doctrine ("no implementation without a committed decision record"), this ADR is not optional: it either substantiates the claim or forces its retraction.

The claim creates an apparent conflict with ADR-Platform-002, which states that `openkubes/openkubes` *is* the Platform Distribution and Integration Layer. A framework is, by definition, not a distribution. The Yocto Project resolves the same tension explicitly: Yocto is the framework; **Poky** is the reference distribution shipped alongside it so the framework does not remain abstract. OpenKubes has silently been carrying both roles in one repository without naming them.

A second observation from the same repositioning: the framework, if it exists, was not designed upfront. It was extracted retroactively from a working distribution — the contracts, the ADR method, and the contract tests were discovered inside `ok-linux`, `ok-cluster`, and `capi-platform-v4.2` (ADR-001), not invented ahead of them.

## Decision

> OpenKubes is a **distribution framework**: the capability contracts, the decision method (ADRs with three-way review), and the contract tests. Everything else — the XRD/Composition wiring, the `ok-*` v1 implementations, the end-to-end examples, the operational assemblies — constitutes the **reference distribution** built with that framework.
>
> `openkubes/openkubes` hosts both, in the same way the Yocto Project hosts both OpenEmbedded-Core and Poky. ADR-Platform-002 is hereby re-read, not superseded: "Platform Distribution and Integration Layer" describes the *reference distribution* role of this repository; the framework role (contracts, ADRs, contract tests) sits above it.

### What the framework materially is

The word "framework" raises code expectations (an SDK, generators, a runtime). The OpenKubes framework is none of these. It consists of exactly three artifact classes:

1. **Capability Contracts** — the framework's API towards distribution builders
2. **The decision method** — ADRs, forcing-consumer discipline, three-way review
3. **Contract Tests** — the framework's verification instrument (and, eventually, its conformance suite — see Consequences)

### The chain, re-read from the framework perspective

| Chain element | Platform reading (until now) | Framework reading (this ADR) |
|---|---|---|
| Capability | What the platform can do | The framework's vocabulary — what a distribution *may* contain |
| Contract | Interface between platform layers | The framework's API towards distribution builders |
| Implementation Profile | Tool choice (Talos, Longhorn, …) | The act of building a distribution — authoring or selecting profiles *is* distribution work |
| Provider Values | Site-specific configuration | A distribution *instance* — never a framework artifact (this retroactively explains why `ok-cluster` must remain private) |
| Contract Tests | Provisioning gate (ADR-018) | The framework's conformance suite in embryo |

### Boundary clarification (re-reading, not contradiction)

The README states "each repository owns exactly one capability contract." This ADR sharpens that formulation: capability contracts **live** in `openkubes/openkubes` (the framework); the `ok-*` repositories are **v1 reference implementations** of those contracts and belong to the reference distribution. They are replaceable — a distribution that swaps `ok-storage` for its own storage implementation, while passing the storage contract tests, is still an OpenKubes distribution. This is the precise sense in which "OpenKubes owns the contracts, not the components" (ADR-001) extends to the framework level.

## Acceptance Condition

Following the ADR-020 pattern, this ADR remains **Draft** until a forcing consumer exists for the framework claim itself:

> **A first external distribution** — an assembly not built by the core team, with its own implementation profile selection and its own Provider Values, running against the OpenKubes capability contracts.

What does *not* satisfy the condition:

- `ok2-rmf` / Open-RMF (ADR-019): a second **consumer** and a platform **instance**. It validates the contracts (and forced ADR-020 to Accepted), but it does not assemble its own distribution.
- Additional internal clusters: instances of the reference distribution, not distributions.

Until the condition is met, the public claim is a **thesis with a defined falsification criterion**, and this ADR is its honest record.

## Rationale

- **The framework is younger than its first distribution, by design.** A framework invented before its distributions would violate the forcing-consumer principle ("no structure without a forcing consumer"). A framework extracted from a working distribution is evidence that the abstraction is real. "Discover, don't invent" applied to the project's own identity.
- **The Yocto analogy is structural, not rhetorical.** Yocto is not a Linux distribution; it is the framework from which distributions fall out, with Poky as the shipped proof. It also answers the delineation question towards kubespray and Cluster API: their layer is provisioning; the OpenKubes layer is contracts. Historically, OpenEmbedded existed before anyone called it a framework — the same bootstrap order as here.
- **ADR-001 already carries the thesis.** "Contracts, not components" *is* the framework claim avant la lettre; this ADR extends it one level up rather than introducing a new principle.
- **This ADR heals a doctrine breach.** The README repositioning shipped before a decision record existed. Recording the claim as a Draft with an acceptance condition — rather than declaring it Accepted by marketing fiat — is the only resolution consistent with the project's own rules.
- **Honest status is a strength.** Declaring the framework thesis Accepted on the evidence of zero external distributions would be the exact "structure without a forcing consumer" failure the doctrine exists to prevent.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Amend ADR-002 instead of a new ADR | Hides the project's identity-level decision in a footnote to a repository-scoping decision; the knowledge graph would have no explicit node for the framework thesis |
| Declare the ADR Accepted now, citing ok2-rmf | ok2-rmf is an instance/consumer, not a distribution; accepting on this evidence would violate the forcing-consumer principle the ADR itself invokes |
| Retract the framework claim until a distribution exists | Loses the thesis's forcing function; the claim with a published falsification criterion actively invites the consumer that would prove it |
| Name the reference distribution now (a "Poky" for OpenKubes) | Structure without a forcing consumer: with only one distribution in existence, a distinguishing name has nothing to distinguish. The name becomes due the day a second distribution appears |
| Supersede ADR-002 | ADR-002's decision remains correct for the reference-distribution role; per the ADR-003 precedent, history is re-read, not deprecated |

## Consequences

**Positive:**

- The public claim and the decision record are reconciled; the doctrine breach of 2026-07-16 is closed
- Every chain element gains a second, sharper reading (table above) without any artifact changing
- The privacy of `ok-cluster` Provider Values is now explained by the architecture instead of by policy
- A future conformance programme has a defined seed: contract tests certify a distribution's claimed capabilities ("Built with OpenKubes" becomes verifiable). **Trigger:** the same first external distribution; no conformance work before then
- The naming question for the reference distribution is explicitly deferred with a defined trigger

**Negative / trade-offs:**

- The project publicly claims to be a framework while its own decision record says "thesis, pending proof" — this asymmetry must be tolerated and, in talks, honestly presented (it is also a compelling story)
- The README sentence "each repository owns exactly one capability contract" needs a follow-up wording adjustment to match the boundary clarification
- Two roles in one repository (framework + reference distribution) demand ongoing discipline in reviews: "is this file a framework artifact or a distribution artifact?"

**Neutral:**

- No repository moves, no code changes, no renames follow from this ADR
- ADR-Platform-002 remains Accepted; its scope is narrowed by re-reading, consistent with the ADR-003 precedent
