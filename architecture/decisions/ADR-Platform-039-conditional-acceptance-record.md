# ADR-Platform-039 — Conditional Acceptance Decision Record

**Date:** 2026-10-19

**Scope:** OK-183 review of the persistent-capacity amendment and remaining
Namespace-profile obligations. Related epic: OK-178.

**Status:** Conditional architectural direction recorded; final acceptance pending.
The [parent ADR](ADR-Platform-039-developer-workspace-contract.md) stays **Proposed**.

**Decision-holder:** Arash Kaffamanesh.

**Source:** [OK-183 review comment 15047](https://kubernauts.atlassian.net/browse/OK-183?focusedCommentId=15047),
2026-10-19, reviewing comment 15042 and the
[acceptance package](https://kubernauts.atlassian.net/wiki/spaces/OpenKubes/pages/3173711873).

## Decision

The reviewer authorized **REVISE → conditional GO for ADR acceptance**, approving
architectural direction and the amendment in principle, with clarification, while
expressly withholding the final transition to Accepted.

1. **Decision 1 — accepted in principle with clarification:** retain the
   provider-neutral §4 runtime-capacity rule. Configuration validity and operator
   audit claims are separate from independently executed runtime enforcement
   evidence for every advertised backend under user namespaces. The
   [dated amendment](ADR-Platform-039-developer-workspace-contract.md#amendment-note-2026-10-19--persistent-capacity-and-conditional-acceptance)
   records the clarification; no declaration certifies a backend automatically.
2. **Decision 2 — accepted as mandatory readiness gates:** preserve INV-039-5/6/9/10,
   N10/N11/N12 and O02/O03 as partial, neither met nor waived. The
   [nine-gate register](ADR-Platform-039-readiness-gates.md) assigns scope, owners,
   acceptance criteria and unblock conditions. The decision authorizes recording
   the gates, not asserting that their missing behavior has been delivered.

**2026-10-20 — reviewer clarification, [c15059](https://kubernauts.atlassian.net/browse/OK-183?focusedCommentId=15059):**
Suchit retains documentation, acceptance evidence and independent verification
only. The gate register proposes owning areas for all nine implementation gates;
each is **unconfirmed — awaiting Arash**, so the earlier TBD ownership remains
unresolved. N10 remains **PARTIAL/open**: ADR-Platform-011 Secret Contract is the
**Accepted/normative** required baseline while its GitOps Implementation Profile
remains **Proposed**. Harness checkout-only credentials and bounded scans are
shown; scoped contract delivery for DeveloperWorkspace is not demonstrated and
still requires independent live proof. O03 remains **PARTIAL/open**: no blanket
exception to Review being more restrictive than Development; any exception needs
an explicit human architecture decision, threat/risk rationale and concrete
security evidence, with no assumed approval. c15047's capacity decision stands.
ADR-Platform-039 stays **Proposed**; conditional architectural GO permits
develop/test only, without full profile conformance or production readiness
acceptance. Preserve all historical evidence revisions and the 42-row mapping
(32 met / 9 partial / 1 conditional). Remaining epic cross-links and User/Operator
Guide alignment still require completion before final review.

## Explicit outcomes

| Outcome | Authority boundary |
| --- | --- |
| GO | Develop and test against the proposed DeveloperWorkspace contract. |
| NO-GO | Declare the Namespace reference profile fully conforming or production-ready. |
| NO-GO | Offer a production DeveloperWorkspace capability until its relevant readiness gates are independently satisfied and production approval is given. |

Execution authority does not confer merge, release, deployment or status-transition
authority. This record is neither a waiver nor a production approval.

## Final review conditions

Suchit Thakkar owns documentation and evidence preparation, based on OK-178
Ownership assigning him execution of the remaining delivery. Each readiness gate's
implementation owner is **TBD — to be confirmed by Arash Kaffamanesh (decision holder)**.
Arash Kaffamanesh retains the architecture decision and final approval. These are
accountability roles, not assertions of ticket assignments.

Before any ADR status change, submit the final reviewable ADR amendment/decision
PR, Living Architecture F1/F2/F5 revision, aligned User/Operator Guide and public
non-claims, updated 42-row acceptance package, gate register and completion
evidence for the decision-holder's explicit final approval. Resolve OK-178 epic
and cross-links and complete its DoD. OK-178 and OK-183 remain open pending that
decision and Epic DoD completion. Preparing this record does not publish the
documentation revisions or resolve the cross-link policy on the reviewer's behalf.

## Evidence boundary

The reviewed package accounts for 42 rows: 32 met, nine partial and one conditional
(`met-if-amendment-accepted`). Its 16/16 required evidence items are evidence at
their recorded scopes, assembled from separate runs. No single complete live
acceptance run on the proposed profile is established. E06 and E14 remain
harness-scope evidence only. The standalone storage persistence fixture extends
no workspace-profile guarantee. Historical evidence pins, verdict strings and
outcomes remain unchanged; this decision supplies no new runtime proof and does
not upgrade any partial row to met.
