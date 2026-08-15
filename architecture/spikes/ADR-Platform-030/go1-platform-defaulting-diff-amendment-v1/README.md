# OK-141 OpenSearch API-defaulting diff amendment

The v7 Core sync established the full platform runtime, but Argo still reports
one OpenSearch StatefulSet as `OutOfSync`.  A bounded immutable render/live
comparison found no desired semantic value mismatch.  Every remaining field is
live-only Kubernetes API defaulting, including pod defaults and defaulted
`volumeClaimTemplates` fields.

This offline amendment adds one exact `ignoreDifferences` rule to the Core
Application.  It is restricted to:

```text
apps/StatefulSet/ok-observability/ok-observability-opensearch
```

Only the 18 observed default-field paths are ignored.  The amendment does not
ignore a whole spec, a whole container, a managed-fields manager, another
resource, or any desired semantic value.  It also does not enable
`RespectIgnoreDifferences=true`, so this remains comparison semantics rather
than a request to omit fields during sync.

Because comparison behavior is part of Platform semantics, this produces
`minimal-observability-v8` and new `P`, `R`, and `FixtureDigest` identities.
The source revision, desired resource set, provider values, and sync options
remain unchanged.

This checkpoint is `NO-GO`.  It does not amend the live Applications, retry the
failed Core operation, prune hook resources, roll back, clean up, or inject a
failure.
