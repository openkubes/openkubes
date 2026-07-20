# The OpenKubes Platform Engineering Method

> This document is a living projection of the architectural principles
> established by the OpenKubes Platform ADRs. It does not define
> architecture; it summarizes the engineering method that emerged from it.
>
> Every principle in this document cites the committed ADRs it emerged from.
> A principle without a committed ADR does not belong here.

*Projection state: ADR-Platform-001 … ADR-Platform-017 (as of commit `8e61412`).*

---

## Why this document exists

OpenKubes is developed using a contract-first platform engineering approach.
This document explains how architectural decisions are discovered, evaluated,
and formalized. It is intentionally independent of any single technology: the
same method can be applied to robotics fleets, IoT platforms, or AI runtimes.

[The Immortal Mind](https://blog.kubernauts.io/the-immortal-mind-d960cc83c065)
explains **why** OpenKubes exists. This document explains **how** we build it.
The ADRs record **what** was decided.

---

## The layer model

Every architectural element of OpenKubes lives on exactly one of these layers:

```
                Changes frequently
                       ▲
                       │
        Provider Values          (IPs, schematics, storage classes, regions)
        Implementation Profiles  (Talos, Longhorn, ArgoCD, …)
        Constraint Envelopes     (datacenter, constrained-edge)
        Contracts                (guarantees a capability must honor)
        Capabilities             (OS, Storage, GitOps, AI Runtime, …)
        Platform Principles      (this document)
                       │
                       ▼
                 Changes rarely
```

The discipline that follows from it:

**Architecture changes should happen as low in this stack as possible.**
A new provider should change provider values, not a contract. A new
deployment target should add a profile or fall under an existing envelope,
not invent a capability. When a change is forced upward — a profile change
that requires a contract change — that is a signal worth an ADR, not a
quick edit.

This also yields a simple architecture metric: the further down the stack
your changes routinely land, the healthier the architecture.

The vocabulary above is deliberately closed. A proposal that cannot be
expressed in these six terms is a signal to re-examine the proposal, not to
extend the vocabulary.

---

## Principles

Each principle cites the committed ADRs it emerged from. Principles marked
*distilled* are later condensations of decisions, not verbatim quotes.

### 1. Contracts, not Components

*ADR-Platform-001.*

OpenKubes owns the guarantees a capability must provide — not the software
that provides them. Talos is not the OS capability; it is one implementation
that satisfies the OS contract. Longhorn is not storage; it satisfies the
`ok-storage-*` contract classes (ADR-009: "Storage implementations are
replaceable. Storage capabilities are not."). Components are replaceable.
Contracts outlive them.

### 2. A good abstraction explains existing architecture

*ADR-Platform-001, ADR-Platform-003.*

An abstraction earns its place by explaining decisions that already exist —
not by describing future plans. ADR-003 states it directly: "Good
abstractions explain the past." ADR-001's claim was validated precisely
because it could explain why `capi-platform-v4.2` looked the way it did,
years before that sentence was written. If a proposed contract cannot point
to running systems it describes, it is speculation.

### 3. Understand before you change

*ADR-Platform-003, ADR-Platform-004; reaffirmed in ADR-Platform-005.
("Erst genau verstehen, dann ändern.")*

Architecture archaeology precedes architecture change. The question is "what
problem did this solve, and does it still exist" — not "is this code old"
(ADR-003). Legacy artifacts are read and mapped before they are renamed,
refactored, or removed. A change to a system you cannot explain is a gamble,
not an engineering decision.

### 4. Redundancy lives on exactly one layer

*ADR-Platform-009 (Decision 3).*

Every failure domain is owned by exactly one layer. Storage replication is
owned by the host cluster (Longhorn replica=2), not restacked inside the
workload clusters — nested distributed storage would multiply write
amplification and failure modes for no gain. Duplicated redundancy is not
extra safety; it is undefined behavior during recovery. (RAID1 × replica=2
is not a violation: disk failure and node failure are different domains on
different layers — ADR-009.)

### 5. One cluster. One name. One credential source.

*ADR-Platform-013.*

Every registered cluster has exactly one canonical name and exactly one
source of credentials. Any state that violates this invariant — orphaned
secrets, duplicate ProviderConfigs — is a defect, not a variant.

### 6. A second consumer forces the contract

*ADR-Platform-013; reinforced by ADR-Platform-016.*

While a capability has one consumer, its interface is indistinguishable from
its implementation. The second consumer — an external cluster registering
against the platform (ADR-013), an edge profile presupposing OS guarantees
(ADR-016) — forces the separation: what is contract, what was incidental.
We do not write contracts in anticipation of consumers; we formalize them
when the second consumer arrives.

### 7. Discover, don't invent

*Distilled from ADR-Platform-001; first stated explicitly during the
formalization of ADR-Platform-016.*

Structure — contracts, directories, conventions, this document — is not
designed up front. It is extracted when repeated practice proves a pattern.
ADR-016 recorded an OS contract that ADR-001 had asserted and real operation
had validated; it did not propose a new one. Several ADRs even announce the
formalization before it happens: ADR-009's outlook names the coming
Capability→Contract→Profile generalization; ADR-014 flags constraint
envelopes as an "emerging concept." In each case the ADR that generalizes
arrives only after the pattern has appeared on its own. The method applies to
itself: this document exists only because its principles were used many times
before they were written down.

### 8. A second constraint envelope forces the guarantees

*ADR-Platform-017; precedents in ADR-Platform-009, -012, -016.*

A capability's contract can stay valid while its guarantees fail to survive a
change of deployment environment. Storage guarantees that hold in the
datacenter (replicated, RWX) do not hold on a single-node edge device
(ADR-009's capability matrix already separates `ok-storage-local` from the
replicated classes); image availability differs between connected pulls and
air-gapped mirroring (ADR-012); the OS contract was written envelope-aware
from the start (ADR-016). ADR-017 formalizes the pattern: **constraint
envelopes qualify guarantees, not capabilities.** Guarantees are made
explicit when a second real envelope demonstrates the implicit ones do not
hold — the guarantee-level counterpart of Principle 6.

---

## How decisions flow

The chain from business need to running system:

```
Requirement            what the platform must achieve
    ↓
Capability             which stable ability answers it (OS, Storage, …)
    ↓
Contract (ADR)         which guarantees that capability must honor
    ↓                  (qualified per constraint envelope — Principle 8)
Implementation Profile which component satisfies the contract
    ↓
Provider Values        the concrete parameters of one installation
    ↓
Jira / Commits         the work that realizes it
```

This is the recurring schema ADR-009 first named
("Capability → Contract → Implementation Profile → Provider-specific
Values") and ADR-017 generalized across envelopes. Selection always runs
top-down: not *"Talos?"* but *which contract → which guarantees → which
envelope → which implementation satisfies them here?*

---

## Review checklist

Before opening a new ADR:

1. Which requirement is this answering?
2. Which capability does it belong to? Does that capability exist?
3. Does a contract for this capability already exist?
4. Which constraint envelope(s) does it apply to? (Silence about envelopes
   is no longer a valid contract state — ADR-017.)
5. Is this a new guarantee, or a new implementation of an existing one?
6. Would a new implementation profile or provider value suffice?
7. Is an ADR necessary at all — or is this a Jira ticket?

If the answer lands on layers below "Contract", no ADR is needed.
That is the desired outcome, not a shortcut.

---

## Relationship to the ADRs

The ADRs are the source of truth; this document is a derived view — in the
same way `okgraph.py` is a derived, disposable projection of Git. When this
document and an ADR disagree, the ADR wins and this document is corrected,
because the ADR is the historical record of the architectural decision.
ADR evolution follows the lifecycle convention in
[`architecture/decisions/README.md`](../architecture/decisions/README.md):
accepted ADRs are historical records, extended or clarified through new ADRs
rather than rewritten.
