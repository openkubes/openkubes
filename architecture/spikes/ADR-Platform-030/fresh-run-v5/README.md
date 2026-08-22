# OK-141 fresh-run package v5

This additive package binds the reviewed Phase-R v6 fixture to one complete
twelve-stage OK-147 runner plan and supersedes v4 for the next live run. It
retains v1, v2, v3 and v4 as historical evidence while binding the complete runner
published from `ok-cluster` source
`cd180dd8127de82973295ee9913ad549e9331a33`.
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
python3 generate_fresh_run_v5.py \
  --runner-image ghcr.io/openkubes/ok-cluster-runner@sha256:<digest> \
  --runner-publication-receipt /path/to/publication-receipt.json
python3 verify_fresh_run_v5.py
python3 -m unittest -v test_fresh_run_v5.py
```

Completing or reviewing this package does not authorize an absence preflight,
credential use, stage grant, Kubernetes write, cleanup, retry, outage or
failure injection.

## Bound checkpoint

```text
runner source:  cd180dd8127de82973295ee9913ad549e9331a33
runner image:   ghcr.io/openkubes/ok-cluster-runner@sha256:bae9f0fb2e0dbacd2774435fb7ea4471c753e19fbe2b23863dd4fac05bc5ee02
plan digest:    sha256:b3e8eb5609f750fc105b774d548361aa101dcd6d3e0cd3086f4cdabe4f81c170
authorization:  NO-GO
```

The updated executable identity produces a new plan identity. The semantic
cluster intent remains bound to the same Phase-R-v6 `R`, `E`, `P` and fixture
identities; none of those historical identities is reinterpreted.
