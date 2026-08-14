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

## Run

From `platform/ai/platform-diagnostics`:

```bash
make verify
```

The default harness starts Profile B on an ephemeral loopback port and sends the
three real HTTP requests through the same `ProviderClient` used for an external
provider. To test another provider without changing the suite:

```bash
DIAGNOSTICS_BASE_URL=http://127.0.0.1:8080 \
DIAGNOSTICS_RBAC_PATH=profiles/kagent/rbac.yaml \
DIAGNOSTICS_BEARER_TOKEN=<consumer-token> \
make verify
```

The in-process Profile B run uses a synthetic consumer token. External runs
must provide the provider's consumer bearer token; it is sent only to the
configured diagnostics endpoint and is never printed by the suite.

`OPENAPI_SPEC` may point at another checkout of the normative specification;
this is useful while a contract change and its conformance implementation are
reviewed on stacked branches.
