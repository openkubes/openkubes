# ADR-Platform-017: Constraint Envelopes

**Status:** Accepted — three-way review completed (Arash / Claude / GPT, 2026-07-12)
**Date:** 2026-07-12
**Deciders:** Arash Kaffamanesh
**Extends:** ADR-Platform-009 (Storage), ADR-Platform-011 (GitOps/Secrets), ADR-Platform-012 (Images), ADR-Platform-016 (OS)
**Related:** ADR-Platform-014 (Constrained Edge Profile), OK-74, OK-73, OK-63

---

## Context

Four independent capability decisions ran into the same problem and solved it
the same way without naming it:

| Precedent | Capability | What happened |
|---|---|---|
| ADR-Platform-009 → 014 | Storage | Datacenter storage guarantees (replicated block, RWX) proved unachievable on constrained edge nodes; ADR-014 had to scope them retroactively |
| ADR-Platform-012 | Images | Image availability guarantees differ fundamentally between connected pulls and air-gapped mirroring / golden images (OK-59) |
| ADR-Platform-011 | Secrets | The secret contract left tool selection open; the real constraint is whether secret material can be reconciled without an always-on external store |
| ADR-Platform-016 | OS | The OS contract was written envelope-aware from the start (datacenter vs. constrained edge), learning from the storage precedent |

The pattern: **a capability's contract stayed valid, but its guarantees did
not survive a change of deployment environment.** Each time, the second
environment forced the guarantees to be made explicit — exactly as a second
consumer forces a contract to be separated from its first implementation.

The repeated appearance of the same architectural pattern across independent
capability decisions indicates that Constraint Envelopes are a platform
concept rather than a capability-specific design technique.

This ADR formalizes the pattern. It is the first ADR to use the `Extends:`
relationship defined in the ADR lifecycle convention
(`architecture/decisions/README.md`, commit `df3a673`).

## Decision

1. **A Constraint Envelope is a named set of environmental constraints under
   which contract guarantees are evaluated.** Constraints include (not
   exhaustively): network connectivity and reachability of external services,
   compute and storage capacity, node redundancy, physical access, and
   operational reachability of the cluster by the platform team.

2. **Constraint Envelopes qualify guarantees, not capabilities.** A
   capability exists once and its contract exists once. What varies per
   envelope is which guarantees the contract can honor, and how strongly:

   ```
   Capability      (one)
       │
   Contract        (one)
       │
   Guarantees      (qualified per envelope)
       │
   Implementation
   Profile         (selected per envelope)
   ```

   An envelope never creates a second contract. If two envelopes require
   contradictory *interfaces* rather than differently-scoped *guarantees*,
   that is a signal the capability is cut wrongly — not a case for a new
   envelope.

3. **Two envelopes are defined, because two exist in practice:**

   - **`datacenter`** — nodes with stable connectivity to platform services
     and external registries/stores, sufficient capacity for replication,
     operational reachability at all times. The implicit envelope of
     ADR-Platform-001 through -013.
   - **`constrained-edge`** — nodes that are resource-constrained,
     intermittently connected, and not operationally reachable on demand.
     Redundancy lives in the fleet layer, not the node; nodes are managed
     because they eventually reconcile, not because they are reachable
     (ADR-Platform-014).

   No further envelopes are defined in this ADR. Candidates (air-gapped,
   see OK-59) are added when a real deployment forces them — discover,
   don't invent.

4. **The reconcilability rule.** A guarantee that depends on an external
   service is valid only in envelopes that guarantee reachability of that
   service. The canonical instance, extending ADR-Platform-011:

   > Secret material must be reconcilable within the constraint envelope of
   > the consuming cluster. Mechanisms requiring an always-on external store
   > are valid only in envelopes that guarantee the necessary connectivity.

   Consequence for ADR-011's open tool selection: it becomes an
   implementation-profile decision per envelope — in `datacenter`, ESO, SOPS,
   or Sealed Secrets are all admissible; in `constrained-edge`, only
   mechanisms that reconcile without a permanently reachable external store.

5. **Contract authoring rule.** From this ADR on, a capability contract
   either declares its guarantees per envelope, or declares itself
   envelope-invariant — explicitly. Silence about envelopes is no longer
   a valid contract state. Existing contracts are not rewritten (lifecycle
   convention); they are qualified by this ADR and, where material, by
   follow-up decisions (OK-73 for storage).

6. **The pattern is named and normative:** *a second constraint envelope
   forces the guarantees.* Guarantees are not enumerated speculatively for
   hypothetical environments; they are made explicit when a second real
   envelope demonstrates that the implicit ones do not hold. This is the
   guarantee-level counterpart of *a second consumer forces the contract*
   (ADR-Platform-013, -016).

## Consequences

**Positive:**
- OK-73 is unblocked: ADR-Platform-009's storage guarantees can now be
  envelope-scoped by a small extending decision instead of a rewrite.
- ADR-Platform-011's unresolved secrets question dissolves into an
  implementation-profile choice per envelope — no amendment to ADR-011
  needed; only an editorial back-reference (`Extended by: ADR-Platform-017`).
- ADR-Platform-016's envelope-aware structure is retroactively explained by
  a platform rule instead of being a one-off precaution.
- Contract reviews gain a mandatory question: *which envelope?* — closing
  the gap where guarantees silently assumed datacenter conditions.
- The platform engineering method gains its missing principle with four
  committed precedents behind it.

**Negative / Accepted:**
- Every future contract carries envelope bookkeeping, even when it declares
  invariance — a small, deliberate authoring cost.
- Two envelopes are a coarse partition; real deployments may straddle them.
  Accepted until a third real envelope forces refinement.
- No tooling enforces envelope declarations yet; enforcement is by review.

**Revisit triggers:**
- A third real deployment environment (e.g. air-gapped, OK-59) → new
  envelope definition, extending this ADR.
- Two envelopes demand contradictory interfaces for one capability →
  capability cut is wrong; new capability decision required.
- Envelope definitions need machine-readable form (XRD parameters,
  okgraph node type) → follow-up implementation ticket, not an ADR.

## Out of Scope

- Defining additional envelopes (air-gapped, cloud, orbital) without a
  forcing deployment
- Envelope-scoping the storage guarantees themselves (OK-73, extends
  ADR-Platform-009 separately)
- Tooling/schema enforcement of envelope declarations
- Fleet-layer mechanics for constrained edge (OK-63 spikes)

## References

- OK-74 — Constraint Envelope ADR (this decision)
- OK-73 — ADR-009 amendment: envelope-scoped storage guarantees (unblocked)
- OK-63 / OK-64–68 — Constrained Edge Profile spikes
- OK-59 — Air-gapped image mirroring / golden-image pattern
- ADR-Platform-009 — Storage Contracts
- ADR-Platform-011 — GitOps / Secret Contract
- ADR-Platform-012 — Image Strategy
- ADR-Platform-014 — Constrained Edge Profile
- ADR-Platform-016 — OS Capability Contract
- `architecture/decisions/README.md` — ADR lifecycle convention (`Extends:` semantics)
