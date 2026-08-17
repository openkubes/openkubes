# OK-141 Platform server-side-apply amendment

This checkpoint responds to live Happy-Run evidence.  The refreshed Argo
target credential restored comparison, and the next exact Core sync proved
that six Prometheus Operator CRDs exceed the Kubernetes client-side
`last-applied-configuration` annotation limit.

The amendment therefore adds `ServerSideApply=true` only to the Core
Application.  It does not change the desired resource set or the immutable
Git source revision.  Because apply mode is durable Platform convergence
semantics, the change produces new `P`, `R`, and `FixtureDigest` identities.

The generator also reconstructs and versions `minimal-observability-v5`,
which had been used by the prior live network amendment but was not present in
the merged Git baseline.  The reconstructed profile is accepted only when its
semantic identity equals the already-bound v5 `P`.

## Current state

- Offline generation and verification: PASS
- New P: `sha256:30946024c91c64d29840bbdd1184d5f1f1e20dde3869505e07e262caef22df7b`
- New R: `sha256:7503b0cd54d5d68243f05e231fe76cb56173a96ba9f2e4f76c83106b30731305`
- New FixtureDigest: `sha256:e83ddec6908ca416d0ddc718a5652ba5db2b4950c26deff1da1ae03b908f028c`
- Live 13-object preflight: STOP before mutation because `ok-mgmt` was unreachable
- Infrastructure mutations from this amendment: none
- Happy Run: incomplete

Resume only after `ok-mgmt` transport is restored.  A new candidate must run
the complete 13-object read-only preflight before any replacement.
