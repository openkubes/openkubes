# OK-141 platform projection v1

This package defines the exact Phase-R v5 Platform projection used by the
future bounded Happy Run. It reuses the reviewed eight-object target-access
set, one AppProject, and the exact three `minimal-observability-v4`
Applications. Runtime annotations are upgraded additively to the current
`R`, `P`, and `FixtureDigest` identities.

The required three-key credential Secret is generated only at runtime. Its
values are non-semantic, never enter Git or evidence, and are not rendered by
the offline command. Argo remains the Platform convergence owner.

This checkpoint performs no cluster contact and grants no mutation,
credential, registration, Platform, GO1-L, or GO-1 authority.

Candidate digest:

```text
sha256:4294218b8032ab5292c44bb1a10ef220099a944619649903f3bc0105d13a4c11
```
