# ADR-Platform-039 — Namespace Profile Readiness Gates

**Date:** 2026-10-19

**Status:** All nine rows remain **partial**, mandatory, open and not waived.

**Authority:** OK-183 Decision 2, recorded in the
[conditional acceptance record](ADR-Platform-039-conditional-acceptance-record.md).
The [contract](ADR-Platform-039-developer-workspace-contract.md) remains Proposed.
This register elaborates obligations without replacing their normative wording.

Suchit Thakkar is the documentation and evidence preparation owner, based on
OK-178 Ownership assigning him execution of the remaining delivery. The
implementation owner for each gate remains to be confirmed by the decision holder.
Arash Kaffamanesh owns architecture and final readiness/production approval.
Each unblock condition requires independently reviewed evidence bound to source
revision, profile, cluster/runtime and exact scope; neither configuration flags,
documentation nor approval of this register closes a gate. Controls must fail
closed until the requested capability can be enforced and proved; do not advertise
unsupported capabilities as conforming.

| Gate / current state | Scope | Owner | Acceptance criteria | Evidence / unblock condition |
| --- | --- | --- | --- | --- |
| INV-039-5 — Explicit connectivity; partial | Per-tool capabilities, beyond endpoint-only Git/inference/MCP reachability. | TBD — to be confirmed by Arash Kaffamanesh (decision holder) | Enforce declared tool permissions; deny undeclared tools even at an allowed endpoint; absent/invalid policy fails closed. | Implement tool-level enforcement; independent live allowed/denied tool calls and missing-policy negatives, with recorded policy and identity. Endpoint reachability alone cannot close this gate. |
| INV-039-6 — Bounded lifecycle; partial | Creation, idling, retention, termination, deletion and lifecycle/Review restrictions. | TBD — to be confirmed by Arash Kaffamanesh (decision holder) | Enforce declared idle/retention/after-retention timers and restrictive Review behavior; invalid lifecycle/restriction declarations fail closed. | Controller implementation plus independent live timed transitions and negative restriction tests across supported lifecycle profiles; distinguish retained storage from deleted compute. Explicit deletion alone is insufficient; Review proof also addresses O03. |
| INV-039-9 — Evidence survives cleanup; partial | Required evidence export before ephemeral deletion. | TBD — to be confirmed by Arash Kaffamanesh (decision holder) | Required export is durably available outside the workspace before deletion; failed, absent or incomplete export blocks cleanup. | Independent controller-driven export-success and export-failure/missing-evidence live tests, with ordering and retained evidence readback after deletion. Harness ordering alone does not close it. |
| INV-039-10 — Historical outcome immutable; partial | Terminal task outcome/evidence separate from current runtime health. | TBD — to be confirmed by Arash Kaffamanesh (decision holder) | Persist terminal outcomes; later drift, infrastructure failure and reconciliation cannot rewrite a completed outcome; reject outcome mutation. | Independent live terminal-task capture followed by drift/failure/reconcile and attempted mutation, comparing durable before/after outcome and evidence identity. Schema separation alone is insufficient. |
| N10 — Secret Contract delivery; partial | Scoped credentials delivered through the accepted Secret Contract (ADR-Platform-011). | TBD — to be confirmed by Arash Kaffamanesh (decision holder) | Use the accepted delivery mechanism with least scope and no runtime ambient credential; missing/unauthorized delivery fails closed without credential leakage. Closure requires either acceptance of ADR-Platform-011, which is currently Proposed, or a decision-holder-approved interim Secret Contract. | Independent end-to-end live Secret Contract delivery and denied/missing-delivery tests, bounded scans and readback of checkout/runtime credential scope. Manually created harness Secrets alone are insufficient. Record the accepted ADR-Platform-011 mechanism or the explicitly approved interim Secret Contract used by the proof. |
| N11 — Observable state; partial | Workspace readiness, failure, termination, task outcome and evidence state. | TBD — to be confirmed by Arash Kaffamanesh (decision holder) | Expose and distinguish full readiness/failure/termination and task outcome/evidence; never treat available Deployment/Ready as task success or acceptance; unproven completion cannot report success. | Independent live success, failure and termination transitions with status readback and durable outcome/evidence links, including later health failure without outcome rewrite (INV-039-10). Pending/running readiness alone is insufficient. |
| N12 — Deterministic cleanup; partial | Automatic lifecycle cleanup, retention, credentials and storage across supported profiles. | TBD — to be confirmed by Arash Kaffamanesh (decision holder) | Implement deterministic automatic cleanup at declared retention boundaries; preserve explicitly retained persistent storage, remove ephemeral credentials/storage, enforce export-before-cleanup and UID-safe ownership. | Independent live automatic expiry/cleanup, retry/idempotence, wrong-UID and blocked-export tests with absence/retention readbacks. Explicit XR cleanup alone does not close it; satisfy INV-039-9 ordering. |
| O02 — Separate authorization; partial | Separately authorized create, attach, mutate and delete, distinct from in-workspace identity. | TBD — to be confirmed by Arash Kaffamanesh (decision holder) | Independently evaluate each operation for requester/operator identities; deny unauthorized and cross-owner access and fail closed on missing authorization; workload execution identity gains no requester authority. | Implement requester/attach boundary; independent live allow/deny matrix for all four operations and direct/indirect bypass attempts. Existing operator-only steering audits do not prove this boundary. |
| O03 — Distinct Review profile; partial | Review lifecycle with restrictive permissions and no implicit promotion authority. | TBD — to be confirmed by Arash Kaffamanesh (decision holder) | Enforce a distinct Review profile with explicitly scoped credentials/tools more restrictive than normal development, following §8's SHOULD. Any exception to being more restrictive than development requires explicit decision-holder approval; the implementer cannot self-approve it. The profile MUST NOT imply merge authority and must fail closed on undeclared capabilities. Local workspace edits/tests remain allowed by §9. | Independent live Review-profile run showing declared review operations succeed and undeclared credential/tool use, source push, merge and deployment authority are denied, plus absent-policy negatives. Generic push denial from another profile is insufficient. Record explicit decision-holder approval for any exception. |

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
