# OK-141 delete D3 preparation v1

Status: **OFFLINE PREPARED / BLOCKED / NO-GO**

D3 is the authoritative CAPI deletion boundary. A fresh preflight binds the
exact disposable Cluster and proves that the provider-access Secret remains
available. The mutating step deletes only the CAPI Cluster with UID and live
`resourceVersion` preconditions using foreground propagation.

All Machine, CAPK, Talos, VM, VMI, DataVolume and PVC cleanup remains owned by
the existing controllers. The provider-access Secret is retained. D4 must later
prove the full controller-owned closure. This checkpoint grants no live delete.
