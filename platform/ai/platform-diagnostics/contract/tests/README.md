# Contract tests (ADR-021)

Six tests. They run against **any** provider profile and must reference no
specific runtime or frontend — that is what makes a backend swap detectable.
The contract requirements are owned by OK-89/OK-90; the executable,
provider-neutral suite and Profile B stub are delivered by OK-91. Existing
provider profiles must be checked against the accepted normative specification
before their conformance can be claimed.

The suite is parameterized over `providers.py`. Tests 1–3 and 5–6 run once per
registered provider; test 4 compares the providers against one another. Adding a
provider to that registry is what keeps the neutrality claim honest — the suite
itself stays free of provider knowledge.

`CONTRACT_VERSION` in `test_contract.py` pins the normative contract version, and
the adapter generator pins its own. The spec path is resolved from the checkout,
so without the pin a branch that has fallen behind validates happily against a
stale contract. That has happened; hence a test rather than a convention.

1. **Schema conformance** — all three functions validate against the normative
   `../openapi.yaml`, whose `info.version` must match the pinned contract
   version, with zero references to a specific runtime or frontend. The Profile A
   facade additionally diffs its framework-generated OpenAPI document against the
   normative file (`profiles/kagent/facade/tests/test_generated_spec.py`): a
   provider with two schema sources otherwise drifts where nobody looks.
2. **RBAC audit** — the Phase-1 provider identity has **no verbs beyond
   `get`/`list`/`watch`**, and no access to `secrets` in any apiGroup. Runs
   against each provider's own RBAC manifest.
3. **Evidence hygiene** — every item has an opaque, stable `EvidenceRef.id`;
   available/partial evidence also carries a `uri`, while output never embeds
   secrets, credentials, or raw payloads.
4. **Backend-swap** — the same consumer suite runs unchanged against **at least
   two independent providers in one run**, and their results are provably not the
   same artifact (identical payloads for every operation means the backend was
   never swapped). A single-provider run cannot detect a provider value that
   leaked into the contract, which is the entire purpose of this test.
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

This starts every registered provider and sends the identical three requests
through the same `ProviderClient`:

* `profile-b` — the deterministic stub, over real HTTP on an ephemeral loopback
  port.
* `profile-a` — the kagent facade, over in-process ASGI. Its cluster and model
  calls are replaced by deterministic doubles; identity enforcement, input
  validation, schema, error mapping and response assembly are the real
  implementation. Hypothesis-bearing investigation paths need a live agent and
  are covered by the facade's own tests.

To add a deployed provider to the same run:

```bash
DIAGNOSTICS_BASE_URL=http://127.0.0.1:8080 \
DIAGNOSTICS_RBAC_PATH=profiles/kagent/rbac.yaml \
DIAGNOSTICS_BEARER_TOKEN=<consumer-token> \
make verify
```

The in-process providers use a synthetic consumer token. External runs must
provide the provider's consumer bearer token; it is sent only to the configured
diagnostics endpoint and is never printed by the suite.

`make verify` also runs the Profile A facade conformance tests. Those tests
exercise all three FastAPI routes against the same normative response schemas,
including bearer rejection, `X-Invocation-Id` correlation, `unknown` cluster
health, self-describing workload/evidence results, stable Evidence IDs, the
rejection of unknown and missing request fields in the normative `Error` shape,
and the consumer-Secret/no-Kubernetes-token deployment guard.

`OPENAPI_SPEC` may point at another checkout of the normative specification;
this is useful while a contract change and its conformance implementation are
reviewed on stacked branches. The version pin still applies, so a mismatched
specification fails loudly instead of silently.

`make verify` runs in CI on every change under `platform/ai/platform-diagnostics`
(`.github/workflows/verify-platform-diagnostics.yaml`).
