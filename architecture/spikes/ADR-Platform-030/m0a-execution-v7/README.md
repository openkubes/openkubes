# OK-141 M0a v7 authority boundary

Status: **OFFLINE ONLY / NO-GO**

The v6 run proved that a temporary ServiceAccount cannot create the reviewed
CAAPH RBAC objects without also receiving the privileges represented by those
objects (or the broad `escalate`/`bind` escape hatches). This checkpoint splits
the unchanged 19-object CAAPH source into two disjoint authority domains:

- the accepted administrator creates the Namespace and seven RBAC objects;
- the temporary installer creates the remaining eleven CAAPH objects.

The temporary installer therefore receives no `escalate` or `bind` permission.
Its fail-closed admission policy enumerates only the eleven exact object
identities. Cluster-scoped and namespaced identities are evaluated by separate
CEL expressions, so a missing `request.namespace` is never interpreted as an
empty namespaced value.

This directory contains only an offline partition and admission-boundary
model. It does not contain an executable candidate or grant, contacts no
cluster, and authorizes neither installation, retry, rollback, publication,
target convergence, nor failure injection.

