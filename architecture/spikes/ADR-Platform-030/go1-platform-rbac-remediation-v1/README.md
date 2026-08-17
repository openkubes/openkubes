# OK-141 minimal Platform RBAC remediation v1

This candidate adds only the three missing `list` permissions proven by the
Platform authorization cause diagnostic. It replaces one namespaced Role and
one ClusterRole using their immediately observed UID and resourceVersion.

The two replacements are not atomic. Argo may reconcile after either succeeds.
On any error the procedure stops and preserves the partial state; it performs no
retry, rollback or cleanup.
