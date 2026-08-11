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
  evidence URI.

Run the complete static and negative-test matrix with:

```bash
make verify
```

The fixtures are deterministic contract examples, not substitutes for live
cluster checks. In particular, the RKE2 profile declares `host_journal` and
`node_shell` as available only when the deployed provider has collectors that
produce retrievable evidence references. Record live validation results under
`evidence/`.

## Files

| Path | Purpose |
|---|---|
| `profiles/*.yaml` | Talos/RKE2 capability declarations and required evidence outcomes |
| `fixtures/*.json` | contract-identical example responses for both distributions |
| `verify.py` | RBAC, capability, response, and cross-distribution checks |
| `tests/` | positive and mutation-based negative tests |
| `evidence/` | dated live-cluster validation records without credentials or raw logs |
