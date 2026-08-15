# Talos/RKE2 provider conformance (OK-95)

This directory verifies the distribution-specific parts of Profile A without
changing the public ADR-021 contract. It enforces these invariants:

- the provider ServiceAccount is limited to `get`, `list`, and `watch`;
- Secrets and RBAC wildcards are forbidden;
- Talos and RKE2 declare the same `provider_capabilities` keys and return the
  same response shape;
- requested but unsupported evidence is returned as `status: unavailable`
  with a non-empty reason, never silently omitted; and
- supported evidence is returned as `status: available` with a retrievable
  evidence URI; and
- both distribution fixtures validate against the normative `EvidenceBundle`
  schema, including invocation correlation, subject/time-window fields, and
  stable unique `EvidenceRef.id` values; and
- every profile declares its **provenance** — whether a running provider was
  observed, or whether the profile states an expectation.

Run the complete static and negative-test matrix with:

```bash
make verify
```

## Measured or assumed

These checks prove that the matrix is *internally consistent*. For a
distribution nobody has measured they cannot prove it is *right* — a declaration
that no one measured cannot fail a static check, it can only be wrong. Each
profile therefore carries a `provenance` block, and `verify.py` reports it:

| Distribution | Provenance | Meaning |
|---|---|---|
| Talos (`ok-ai`) | `measured`, 2026-08-11 | a running provider was audited and a live `collect_diagnostic_evidence` response observed |
| RKE2 (`ok-infra`) | `assumed` | Profile A is not installed; the profile states what the provider is expected to declare |

`make verify` reports the gap and exits zero, so CI keeps running the static
checks. `make verify-measured` is the acceptance gate: it fails while any
distribution is still an assumption. An assumed profile must name the steps that
would close the gap — an open gap without a route to close it is not a plan.

The fixtures are deterministic contract examples, not substitutes for live
cluster checks. Record live validation results under `evidence/` and flip the
profile to `measured` in the same change.

## Files

| Path | Purpose |
|---|---|
| `profiles/*.yaml` | Talos/RKE2 capability declarations and required evidence outcomes |
| `fixtures/*.json` | contract-identical example responses for both distributions |
| `verify.py` | RBAC, capability, response, and cross-distribution checks |
| `tests/` | positive and mutation-based negative tests |
| `evidence/` | dated live-cluster validation records without credentials or raw logs |
