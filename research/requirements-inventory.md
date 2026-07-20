# Requirements Inventory — Open Spike

> **This is a research document, not an architectural decision.**
>
> It is the working record of an *open* spike: an investigation into whether
> OpenKubes has a first-class Requirement layer that it has not yet named.
> The question is genuinely open — the outcome may be YES, NO, or NOT YET, and
> it has not been reached at the time of writing.
>
> **The seven items below are candidates, not commitments.** They are
> requirements *extracted* from the context of existing ADRs — discovered, not
> invented — in order to test a hypothesis. Nothing here defines architecture.
> No `requirements/` directory exists, no `REQ-` artifact is authoritative, and
> no ADR points at these entries. If you are looking for what OpenKubes has
> decided, read the ADRs; this is how we investigate whether a decision is even
> warranted.
>
> The verdict, once the spike concludes, will be recorded in the Decision Gate
> section at the end of this same document.

**Spike:** Extract implicit platform requirements from committed ADRs.
**Goal:** Determine whether a first-class Requirement layer naturally emerges
from the current OpenKubes architecture.
**Explicit non-goal:** Do NOT introduce a `requirements/` directory or `REQ`
artifacts. The spike investigates; it does not decide.

Method-phase framing (refined in review). A concept moves through:

  1. observation
  2. repetition
  3. a layer emerges (used as a shared layer, not just repeated)
  4. pattern recognized
  5. formalization

Constraint Envelopes were at stage 4 when ADR-017 formalized them.
**Requirements are at stage 2 at most:** they exist in ADR contexts and
recur, but they are not yet *used as a shared layer*. This document tests
whether stage 3 has actually been reached.

**Same burden of proof, not merely the same process.** Constraint Envelopes
had to earn their existence with four independent precedents before
formalization was allowed. Requirements must clear the same bar — no lower.
Explicit warning against a specific bias here: this layer was surfaced by the
method itself, which makes it *feel* more legitimate than an externally
proposed one. It is not. The origin of a hypothesis does not reduce its
burden of proof. A layer the method exposed still has to prove it exists.

---

## Extracted candidate requirements

Each is lifted from the Context/motivation of a committed ADR — discovered,
not invented. Wording is paraphrased from the source ADR.

| Candidate | Source ADR(s) | One-line statement (as motivated in the ADR) |
|---|---|---|
| R?-self-service-lifecycle | 003, 004, 013 | Operators and teams provision and manage cluster lifecycle through a Kubernetes-native, self-service API — not manual procedures. |
| R?-sovereign-ai | 005 | Provide LLM inference for internal use on owned hardware, local-first, without depending on public cloud GPU. |
| R?-stateful-survivability | 009 | Stateful workloads survive single-node failure; KubeVirt live migration is possible (shared storage prerequisite). |
| R?-repeatable-registration | 013 | Multiple cluster owners register workload clusters into the management plane as a repeatable, non-manual operation. |
| R?-offline-edge-operation | 014 | Run Kubernetes on constrained, remote, unattended hardware that is intermittently connected and not reachable on demand. |
| R?-air-gapped-images | 012 (via 014) | Workload images are available without on-demand registry pulls (mirroring / golden images / delta sync). |
| R?-platform-diagnosis-ai | 015 | Read-only agentic assistance for platform diagnosis (troubleshooting, log analysis, decision-history queries). |

Provisional count: **7 candidates.**

---

## The three tests the spike must apply

A Requirement layer is justified only if the candidates pass these. This is
the actual decision work — the extraction above was the easy part.

### Test 0 — Does the layer already exist? (stage-3 gate)
Before independence/multiplicity: is there any place today where requirements
are treated *as a shared layer* — referenced across ADRs by a common handle,
reasoned about collectively — rather than each living inside one ADR's prose?
If the honest answer is "no, they only exist as per-ADR context," the concept
is at stage 2, and the correct outcome is NOT YET regardless of how the other
tests come out. Stage 3 cannot be skipped by formalizing early.

### Test 1 — Independence
Are these genuinely distinct requirements, or is one a restatement of another
at a different altitude?
- Watch: `self-service-lifecycle` (003/004/013) vs `repeatable-registration`
  (013). Registration may be a *sub-requirement* of lifecycle, not a peer.
  If several "requirements" collapse into one, the layer is thinner than it
  looks.

### Test 2 — Multiplicity (the actual trigger)
Does at least one requirement motivate **more than one** ADR *independently*?
This is the "second consumer forces the contract" test applied to
requirements. If every requirement maps 1:1 to a single ADR, then the
requirement adds no information the ADR context doesn't already carry —
and the layer is redundant.
- Strongest candidate for multiplicity: `offline-edge-operation` appears to
  drive OS (016), Storage (009/014), Images (012), and — via the
  reconcilability rule — Secrets (011/017). **If this holds, it is the single
  best argument for the layer:** one requirement, four contracts, currently
  restated in four separate contexts with no single source.
- `sovereign-ai` may drive both 005 (shared GPU backend) and 015 (agentic AI).

### Test 3 — Forward-traceability value
Is there a real question that a Requirement layer answers and ADR-context
prose cannot?
- "Which ADRs/profiles/commits serve `offline-edge-operation`?" — today
  unanswerable without reading everything.
- "Requirement X changed — what is the impact set?" — no impact set exists.
- This is also the okgraph forward-path question: a REQ node type would let
  the graph traverse Requirement → Capability → ADR → Profile → Commit.

---

## Decision gate (end of spike)

The verdict is one of three — **YES / NO / NOT YET** — not a binary:

- **YES** — several candidates survive Test 1, at least one clears Test 2
  (multi-ADR), Test 3 shows real forward-traceability value, *and* Test 0
  finds the layer is already being used as such. → propose the Requirement
  layer via a small ADR + a REQ format, rewire affected ADRs with
  `Requirement:` metadata (editorial), add the okgraph node type.
- **NOT YET** — the candidates look independent and useful, but Test 0 fails:
  they are not yet used as a shared layer. → do nothing structural; the
  hypothesis is plausible but unproven. Re-run the spike when a concrete
  forcing consumer appears (okgraph forward-path, or a public traceability
  claim in the CNCF talk).
- **NO** — candidates collapse under Test 1, or none clears Test 2. →
  requirements stay in ADR context permanently; discard the `requirements/`
  idea.

All three outcomes are valid findings. A NO or NOT YET is not a failed spike.

**Current status: OPEN.** No verdict has been reached. The tests above have
not yet been worked through; when they are, the outcome is recorded here.

## Open method question (parked, NOT for the method doc yet)
Review raised: "the method exposes missing layers; treat such discoveries as
hypotheses until repeated practice demonstrates formalization." This is itself
a phase-2 observation (seen once: here, with requirements). Do **not** add it
to the method until a *second* instance of the method exposing a missing layer
appears. One instance is not a pattern. Parked deliberately.
