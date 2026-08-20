# OK-141 delete D2 preparation v1

Status: **OFFLINE PREPARED / BLOCKED / NO-GO**

D2 quiesces enablement after D1 removed the disposable GitOps target. A fresh
read-only binding identifies the exact `HelmChartProxy` and exactly one
controller-owned `HelmReleaseProxy`. The bounded mutating step deletes only the
HCP with UID and freshly observed `resourceVersion` preconditions, then observes
both objects until CAAPH removes them.

The runner never deletes the HRP or any Cilium workload resource, never removes
a finalizer and never retries. This checkpoint grants no live authority.
