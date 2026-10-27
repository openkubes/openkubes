# OK-141 Argo runtime refresh candidate v1

The second and final explicitly authorized Core sync failed even though all
five exact ClusterRole prerequisites were present. Follow-up diagnostics proved
that the current registration identity can list/watch ClusterRoles, can perform
a named dry-run update, can perform the same client-side apply in server dry-run
mode, and matches the subject recorded by the failed Argo operation.

This checkpoint prepares the smallest remaining experiment:

```text
exact reads on ok-shared
        ↓
verify argocd-cm + StatefulSet + current Pod
        ↓
graceful UID/resourceVersion-protected Pod deletion
        ↓
wait for one replacement Pod with a new UID
        ↓
bounded exact observation of the Core Application
```

The candidate is intentionally `BLOCKED-NO-GO`. The Core Application has
automated self-heal enabled. Recreating the application-controller may therefore
initiate another reconciliation without an explicit Application operation.
That possibility is semantically a retry and is not covered by the previous
grant, which expressly allowed no further retries.

No credential, cluster contact, restart, Application observation, sync, cleanup
or failure injection is performed by this checkpoint.

## Runtime result

The separately granted execution completed fail-closed:

```text
graceful controller restart       PASS
replacement UID changed           PASS
replacement Running + Ready       PASS (iteration 4)
explicit Application operation    none
Core observation                  40 × 15 seconds
Core health                       Healthy
Core sync                         OutOfSync
blocking condition                SyncError
result                            STOP-PRESERVE-NO-RETRY
```

The Application state did not change once during the bounded observation. A
post-run exact status read showed that Argo now reports four of the five bound
ClusterRoles as `Synced`; only `ok-observability-operator` remains
`OutOfSync`.

Further exact read-only diagnostics found no semantic drift in that role:

```text
rule set                           equal
exact rule sequence                equal
normalized rule sequence           equal
labels and values                  equal
annotations                        equal (empty on all five roles)
aggregationRule                    equal
```

The graceful restart therefore disproves the broad stale-runtime hypothesis.
The remaining boundary is an Argo comparison-state discrepancy for one
semantically equal resource. A further explicit sync remains outside this
run's authorization.
