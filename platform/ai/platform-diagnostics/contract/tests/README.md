# Contract tests (ADR-021)

Six tests. They run against **any** provider profile and must reference no
specific runtime or frontend — that is what makes a backend swap detectable.
The contract requirements are owned by OK-89/OK-90; the executable,
provider-neutral suite and Profile B stub are delivered by OK-91. Existing
provider profiles must be checked against the accepted normative specification
before their conformance can be claimed.

1. **Schema conformance** — all three functions validate against `../openapi.yaml`,
   with zero references to a specific runtime or frontend.
2. **RBAC audit** — the Phase-1 provider identity has **no verbs beyond
   `get`/`list`/`watch`**, and no access to `secrets` in any apiGroup.
   (Mirrors `openclaw`'s `make verify-kubectl`; reused for kagent's SA.)
3. **Evidence hygiene** — every item has an opaque, stable `EvidenceRef.id`;
   available/partial evidence also carries a `uri`, while output never embeds
   secrets, credentials, or raw payloads.
4. **Backend-swap** — the consumer test suite passes unchanged against a stub
   Profile B. If a swap breaks a consumer, a provider value leaked into the contract.
5. **Capability delta** — a provider that declares a capability absent MUST return
   `EvidenceRef.status: unavailable` + `reason` for affected evidence. Silent
   omission is a failure.
6. **Counter-evidence discipline** — every `RankedHypothesis` carries `confidence`,
   `contradicting_evidence_refs`, and `counter_evidence_status`; all supporting
   and contradicting IDs resolve to exactly one `EvidenceRef`, and `not_checked`
   fails a finalized diagnostic result.

> Status: specification only in this branch. Executable tests land with OK-91.
> Recommended shape:
> schema/tests 1,3,5,6 as OpenAPI + JSON-Schema assertions over recorded provider
> responses; test 2 as the in-cluster RBAC probe (see `profiles/kagent/rbac.yaml`
> and the reused `verify-kubectl` target); test 4 against `profiles/_stub-b`.
