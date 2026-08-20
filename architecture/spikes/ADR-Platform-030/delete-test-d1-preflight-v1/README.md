# OK-141 delete D1 target-correlation preflight v1

Status: **OFFLINE-PREPARED / EXPLICIT READ GRANT REQUIRED / NO-GO**

D1 will remove three Argo Applications, one registration Secret and one
AppProject. Before any delete can be considered, this preflight must bind their
current UID/resourceVersion values and prove in memory that all three
Applications still target the exact registered disposable cluster.

The preflight performs six sealed GETs on `ok-shared`. It transiently decodes
only the registration identity needed for comparison. Endpoints, Secret
content and raw Application objects are never persisted. The private output
contains only the five delete identities plus a target-identity digest and is
valid for at most five minutes.

This checkpoint does not authorize the preflight, D1, mutation, deletion,
cleanup, retry, outage or failure injection. A fresh D0-v3 binding and a new
explicit read-only grant are required at execution time.
