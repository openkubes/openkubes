# OK-141 fresh-run package v3

This additive package binds the reviewed Phase-R v6 fixture to one complete
twelve-stage OK-147 runner plan and supersedes v2 for the next live run. It
retains v1 and v2 as historical evidence while binding the complete runner
published from `ok-cluster` source
`fe8b9d578e202d0af50bb621273a632121f6962e`.
It consolidates the exact provider/lifecycle projections,
the corrected CAAPH candidate, bounded network and runtime semantics, the
proven target RBAC boundary, runtime-only target identity placeholders, the
three P9 Applications and the final aggregate evaluator profile.

The package is deliberately non-authorizing:

```text
authorizationState: NO-GO
cluster contact:     false
mutation authority: false
credentials:        absent
```

The CAPI Cluster UID cannot exist before Stage 2. Stages 8, 9 and 10 therefore
carry the exact `RUNTIME-TARGET-IDENTITY-DIGEST-REQUIRED` placeholder. The
runner may replace it only in memory after verifying the Stage-2 lifecycle
receipt; the public artifact bytes and their plan-bound digests remain fixed.

Generation is deterministic for a pinned runner image and its redacted,
pullback-verified publication receipt:

```bash
python3 generate_fresh_run_v3.py \
  --runner-image ghcr.io/openkubes/ok-cluster-runner@sha256:<digest> \
  --runner-publication-receipt /path/to/publication-receipt.json
python3 verify_fresh_run_v3.py
python3 -m unittest -v test_fresh_run_v3.py
```

Completing or reviewing this package does not authorize an absence preflight,
credential use, stage grant, Kubernetes write, cleanup, retry, outage or
failure injection.

## Bound checkpoint

```text
runner source:  fe8b9d578e202d0af50bb621273a632121f6962e
runner image:   ghcr.io/openkubes/ok-cluster-runner@sha256:56a05cb0c2c2ea2838958a6f265e8b4bbf8cd777e0f1ce3a41913095a7a29e64
plan digest:    sha256:fbe8d9eba484d7fbb257648f36ea404fa07562d88ce97608f583836515e95cde
authorization:  NO-GO
```

The updated executable identity produces a new plan identity. The semantic
cluster intent remains bound to the same Phase-R-v6 `R`, `E`, `P` and fixture
identities; none of those historical identities is reinterpreted.
