# OK-141 SSA client-side migration amendment

The first Core sync with `ServerSideApply=true` still failed on six large
Prometheus Operator CRDs.  Live operation evidence proves that Argo accepted
the SSA option.  Offline rendering proves that the manifests themselves do
not contain `kubectl.kubernetes.io/last-applied-configuration`.

Argo CD enables client-side apply migration by default during an SSA sync.
That migration path still reaches the annotation-size boundary.  This
amendment therefore adds exactly one further Core-only sync option:

```text
ClientSideApplyMigration=false
```

This is durable Platform convergence semantics, so it creates a new
`minimal-observability-v7` profile and new `P`, `R`, and `FixtureDigest`
identities.  The desired resource set and immutable Git revision do not
change.  Live execution remains separately bounded and fail-closed.

## Runtime result

The v7 amendment updated all 13 bound objects and the approved Core sync
passed the former annotation-size boundary: 94 resources synchronized.  Four
new monitoring CRDs were not established at Argo's first health check, while
the already-running Prometheus operator predated those APIs by more than six
hours.  A single graceful, UID/resourceVersion-protected operator restart
refreshed discovery without submitting another Argo sync.  The replacement
became Ready, Prometheus became `Available` and `Reconciled`, and its
StatefulSet reached one ready and available replica.

The original Core operation nevertheless terminated `Failed`, preserving its
initial CRD and Prometheus health failures.  Current Application health is
`Healthy`, but sync remains `OutOfSync`: five completed admission-hook
resources require pruning, and the OpenSearch StatefulSet differs only in
API-defaulted live fields in the bounded local render/live comparison.  No
second sync, rollback, general cleanup, or failure injection was performed.

The redacted runtime closure is recorded in
`runtime-closure-v1.json`.  Raw credentials, API objects, logs, UIDs,
resourceVersions, and private execution evidence remain outside Git.
