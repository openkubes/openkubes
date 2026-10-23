# ADR-Platform-039 — Namespace Profile Readiness Gates

**Date:** 2026-10-19

**Status:** All nine rows remain **partial**, mandatory, open and not waived.

**Authority:** OK-183 Decision 2, recorded in the
[conditional acceptance record](ADR-Platform-039-conditional-acceptance-record.md).
The [contract](ADR-Platform-039-developer-workspace-contract.md) remains Proposed.
This register elaborates obligations without replacing their normative wording.

Suchit Thakkar is the documentation, evidence preparation and independent verification
owner only, based on
OK-178 Ownership assigning him execution of the remaining delivery. The
implementation owner for each gate remains to be confirmed by the decision holder.
Arash Kaffamanesh owns architecture and final readiness/production approval.
Each unblock condition requires independently reviewed evidence bound to source
revision, profile, cluster/runtime and exact scope; neither configuration flags,
documentation nor approval of this register closes a gate. Controls must fail
closed until the requested capability can be enforced and proved; do not advertise
unsupported capabilities as conforming.

| Gate / current state | Scope | Proposed implementation owner (for Arash's confirmation) | Acceptance criteria | Evidence / unblock condition |
| --- | --- | --- | --- | --- |
| INV-039-5 — Explicit connectivity; partial | Per-tool capabilities, beyond endpoint-only Git/inference/MCP reachability. | platform security / tool-policy enforcement owners; **unconfirmed — awaiting Arash**. Rationale: Per-tool authorization needs enforcement beyond network endpoint allowlists. | Enforce declared tool permissions; deny undeclared tools even at an allowed endpoint; absent/invalid policy fails closed. | Implement tool-level enforcement; independent live allowed/denied tool calls and missing-policy negatives, with recorded policy and identity. Endpoint reachability alone cannot close this gate. |
| INV-039-6 — Bounded lifecycle; partial | Creation, idling, retention, termination, deletion and lifecycle/Review restrictions. | DeveloperWorkspace Crossplane composition / lifecycle-controller owners; **unconfirmed — awaiting Arash**. Rationale: Idle and retention timers and Review transitions belong to workspace reconciliation. | Enforce declared idle/retention/after-retention timers and restrictive Review behavior; invalid lifecycle/restriction declarations fail closed. | Controller implementation plus independent live timed transitions and negative restriction tests across supported lifecycle profiles; distinguish retained storage from deleted compute. Explicit deletion alone is insufficient; Review proof also addresses O03. |
| INV-039-9 — Evidence survives cleanup; partial | Required evidence export before ephemeral deletion. | DeveloperWorkspace lifecycle / evidence-export controller owners; **unconfirmed — awaiting Arash**. Rationale: The cleanup controller must block deletion until durable export is verified. | Required export is durably available outside the workspace before deletion; failed, absent or incomplete export blocks cleanup. | Independent controller-driven export-success and export-failure/missing-evidence live tests, with ordering and retained evidence readback after deletion. Harness ordering alone does not close it. |
| INV-039-10 — Historical outcome immutable; partial | Terminal task outcome/evidence separate from current runtime health. | DeveloperWorkspace task-outcome / observed-state owners; **unconfirmed — awaiting Arash**. Rationale: Durable terminal outcomes must survive later health changes and reconciliation. | Persist terminal outcomes; later drift, infrastructure failure and reconciliation cannot rewrite a completed outcome; reject outcome mutation. | Independent live terminal-task capture followed by drift/failure/reconcile and attempted mutation, comparing durable before/after outcome and evidence identity. Schema separation alone is insufficient. |
| N10 — Secret Contract delivery; partial | Scoped credentials through ADR-011 Secret Contract, Accepted/normative baseline confirmed by c15059; GitOps Implementation Profile Proposed. Demonstrated: harness checkout-only credentials and bounded scans using manually supplied Secrets. Not demonstrated: scoped contract delivery for DeveloperWorkspace; N10 remains PARTIAL/open. | ADR-011 Secret Contract / GitOps owners, with DeveloperWorkspace composition owners; **unconfirmed — awaiting Arash**. Rationale: Contract delivery must be integrated into the workspace credential boundary. | Use the accepted delivery mechanism with least scope and no runtime ambient credential; missing/unauthorized delivery fails closed without credential leakage. Closure requires delivery through ADR-Platform-011 §Secret Contract, which c15059 confirms as the required baseline. | Independent end-to-end live Secret Contract delivery and denied/missing-delivery tests, bounded scans and readback of checkout/runtime credential scope. Manually created harness Secrets alone are insufficient. Record the ADR-Platform-011 §Secret Contract mechanism used by the proof. |
| N11 — Observable state; partial | Workspace readiness, failure, termination, task outcome and evidence state. | DeveloperWorkspace status / ok-console observed-state owners; **unconfirmed — awaiting Arash**. Rationale: Reconciled status and its consumers must distinguish readiness, task outcome and evidence. | Expose and distinguish full readiness/failure/termination and task outcome/evidence; never treat available Deployment/Ready as task success or acceptance; unproven completion cannot report success. | Independent live success, failure and termination transitions with status readback and durable outcome/evidence links, including later health failure without outcome rewrite (INV-039-10). Pending/running readiness alone is insufficient. |
| N12 — Deterministic cleanup; partial | Automatic lifecycle cleanup, retention, credentials and storage across supported profiles. | DeveloperWorkspace lifecycle-controller owners, with storage / ok-storage maintainers; **unconfirmed — awaiting Arash**. Rationale: Automatic cleanup coordinates retention, credential removal and retained storage. | Implement deterministic automatic cleanup at declared retention boundaries; preserve explicitly retained persistent storage, remove ephemeral credentials/storage, enforce export-before-cleanup and UID-safe ownership. | Independent live automatic expiry/cleanup, retry/idempotence, wrong-UID and blocked-export tests with absence/retention readbacks. Explicit XR cleanup alone does not close it; satisfy INV-039-9 ordering. |
| O02 — Separate authorization; partial | Separately authorized create, attach, mutate and delete, distinct from in-workspace identity. | platform security / DeveloperWorkspace requester-authorization owners; **unconfirmed — awaiting Arash**. Rationale: Create, attach, mutate and delete each require an independent requester authorization boundary. | Independently evaluate each operation for requester/operator identities; deny unauthorized and cross-owner access and fail closed on missing authorization; workload execution identity gains no requester authority. | Implement requester/attach boundary; independent live allow/deny matrix for all four operations and direct/indirect bypass attempts. Existing operator-only steering audits do not prove this boundary. |
| O03 — Distinct Review profile; partial | Review lifecycle with restrictive permissions and no implicit promotion authority. c15059: no blanket exception to Review being more restrictive than Development; any exception needs an explicit human architecture decision, threat/risk rationale and concrete security evidence; approval is not assumed. O03 remains PARTIAL/open. | platform security / Review-profile owners; **unconfirmed — awaiting Arash**. Rationale: Review-specific tool and credential restrictions need security enforcement and exception evidence. | Enforce a distinct Review profile with explicitly scoped credentials/tools more restrictive than normal development, following §8's SHOULD. Any exception to being more restrictive than development requires explicit decision-holder approval; the implementer cannot self-approve it. The profile MUST NOT imply merge authority and must fail closed on undeclared capabilities. Local workspace edits/tests remain allowed by §9. | Independent live Review-profile run showing declared review operations succeed and undeclared credential/tool use, source push, merge and deployment authority are denied, plus absent-policy negatives. Generic push denial from another profile is insufficient. Record explicit decision-holder approval for any exception. |

## Clarifications recorded 2026-10-20 — c15059

[Arash's c15059](https://kubernauts.atlassian.net/browse/OK-183?focusedCommentId=15059)
confirms the following interpretation of the rows above; the acceptance criteria
are retained.

- **N10 — PARTIAL/open:** ADR-Platform-011 §Secret Contract is the
  **Accepted/normative** required architectural baseline; its GitOps Implementation
  Profile remains **Proposed**. Demonstrated today: harness-scoped, checkout-only
  credential delivery and bounded secret/redaction scans using manually supplied
  Secrets. Not demonstrated: scoped credential delivery through that contract for
  DeveloperWorkspace. Baseline recognition supplies no implementation proof. Unblock
  only with independently demonstrated end-to-end contract delivery, scope readback
  and denied/missing-delivery negatives specified in N10; record the mechanism used.
- **O03 — PARTIAL/open:** no blanket exception to Review being more restrictive
  than Development. Any proposed exception requires an **explicit human architecture
  decision, threat/risk rationale and concrete security evidence**. No exception is
  assumed approved; retain the distinct Review-profile positive/negative evidence
  and fail-closed unblock conditions in the row above.
- Every implementation area above is a proposal, **unconfirmed — awaiting Arash**;
  none resolves ownership or assigns implementation to Suchit. Suchit retains
  documentation, acceptance evidence and independent verification only. Arash
  confirms implementation ownership. Conditional GO permits develop/test only;
  ADR-Platform-039 remains **Proposed**, with no full conformance or production
  readiness acceptance. Historical evidence revisions and verdicts are unchanged.

## Owner-assignment plan (proposal, for Arash's confirmation)

1. Each gate has one accountable lead area: the first area named in its row
   (N10: ADR-011 Secret Contract / GitOps; N11: DeveloperWorkspace status; N12:
   DeveloperWorkspace lifecycle controllers). Any second area named is a contributor.
2. Arash names one technical lead per area, or reassigns the gate, in OK-183 or
   the OK-178 epic. Until then the row stays **unconfirmed — awaiting Arash** and the
   gate stays open.
3. A named lead accepts the gate's acceptance criteria, evidence required and unblock
   condition as written; changes to them need Arash's approval.
4. Suchit records the confirmed name in this register and independently verifies
   the evidence before any gate is marked closed. He does not own implementation.

## Closure discipline

Keep each row partial until its implementation and independently reviewed evidence
satisfy its acceptance criteria and unblock condition. Append dated closure
evidence and decision references rather than rewriting historical outcomes.
Overlapping gates share evidence only when the scope is explicit; a proof merged
from separate runs must never be described as one complete live acceptance run.
Satisfying one gate closes no other gate automatically. Capacity certification
remains an additional per-backend requirement in the dated ADR amendment, not a
tenth partial row. Full conformance and production claims remain NO-GO as recorded
in the decision record.

ADR-Platform-039 was accepted as the architectural contract on 2026-10-20
([OK-183 c15102](https://kubernauts.atlassian.net/browse/OK-183?focusedCommentId=15102)).
All nine gates above remain open and mandatory; acceptance neither meets nor waives
any of them and grants no production approval.
