# OK-141 fresh-run package v7

This additive package binds the reviewed Phase-R v6 fixture to one complete
twelve-stage OK-147 runner plan and supersedes v6 for the next live run. It
retains v1 through v6 as historical evidence while binding the complete runner
published from `ok-cluster` source
`4a9a650c4270b2a572e7de4a7d3f3b45b2837330`.
It consolidates the exact provider/lifecycle projections,
the corrected CAAPH candidate, bounded network and runtime semantics, the
proven target RBAC boundary, runtime-only target identity placeholders, the
three P9 Applications and the final aggregate evaluator profile.

The additive `activation-projection/` root closes the package boundary for
execution: it contains the complete Phase-R projection while replacing only
the historical management lifecycle artifact with the exact v7 artifact
already bound by Stage 2. Its manifest binds the raw artifact identities and
the semantic object-set identities. The historical Phase-R v6 projection is
not changed or reinterpreted.

Unlike v6, the cluster-lifecycle stage has two independently hashed inputs.
The second input defines the exact immutable Provider-Access Secret policy;
the private `0600` source kubeconfig is supplied only to the activation bundle.
The additive lifecycle artifact also binds the DEV workload API VIP
`192.168.100.213`. The full-run manifest later binds the independent evidence
collector VIP `192.168.100.214`; both allocations remain subject to an
immediate absence preflight before authorization.

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
python3 generate_fresh_run_v7.py \
  --runner-image ghcr.io/openkubes/ok-cluster-runner@sha256:<digest> \
  --runner-publication-receipt /path/to/publication-receipt.json
python3 verify_fresh_run_v7.py
python3 -m unittest -v test_fresh_run_v7.py
```

Completing or reviewing this package does not authorize an absence preflight,
credential use, stage grant, Kubernetes write, cleanup, retry, outage or
failure injection.

## Bound checkpoint

```text
runner source:  4a9a650c4270b2a572e7de4a7d3f3b45b2837330
runner image:   ghcr.io/openkubes/ok-cluster-runner@sha256:86b5b1175944785d787fcc1b408114d31341c67be90841f896aedc43389f5af2
plan digest:    sha256:4f61e81b3f3dba5a2819e5be93764486d5a936f3fb2ba153a80d5866801af19c
authorization:  NO-GO
```

The updated executable identity produces a new plan identity. The semantic
cluster intent remains bound to the same Phase-R-v6 `R`, `E`, `P` and fixture
identities; none of those historical identities is reinterpreted.
