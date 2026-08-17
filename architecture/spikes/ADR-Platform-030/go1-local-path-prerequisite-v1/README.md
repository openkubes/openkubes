# OK-141 local-path prerequisite v1

The bounded Runtime Binding diagnostic proved that the disposable workload
cluster has a valid identity and `kube-system`, but no `StorageClass/local-path`.
This is consistent with the current `ok-cluster` workflow: Cilium and storage
are separate operations, and `make install-storage` had not been part of the
Happy Run.

This package turns the existing `ok-cluster` storage operation into an exact,
reviewable prerequisite candidate:

- upstream source is locked to `rancher/local-path-provisioner` tag `v0.0.30`,
  commit `c4fdcada94c2e632cd7d9231e73406d554eb40e2` and manifest digest
  `sha256:fe682186...0045e`;
- the source operation is traced to `openkubes/ok-cluster` commit
  `c4bb72e368bdedb92d75485ce9972d86e8a75210`, target `install-storage`;
- both referenced container images are pinned by registry digest;
- the privileged Pod Security labels and default-StorageClass annotation are
  included in the projected objects instead of being patched afterwards;
- exactly nine objects may be created, only after nine exact GETs prove that
  the complete set is absent;
- any partial failure stops and preserves state without retry or cleanup.

The candidate is `NO-GO`. It does not reuse Resume v6, does not install
anything, and does not authorize Runtime Binding or Platform continuation.
