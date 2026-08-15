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
