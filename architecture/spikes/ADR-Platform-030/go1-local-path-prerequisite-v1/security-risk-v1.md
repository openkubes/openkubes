# OK-141 local-path prerequisite security and failure boundary

The proposed disposable DEV prerequisite deliberately retains the behavior of
the existing `ok-cluster install-storage` target, but binds it more narrowly.

## Accepted only by a later explicit decision

- A DEV administrator credential reads the existing workload Kubeconfig
  Secret and creates the exact nine-object set on the disposable cluster.
- Creation is not atomic. A failed object may leave a partial installation;
  the executor stops, preserves it, and performs no automatic retry or cleanup.
- The namespace uses the privileged Pod Security profile. Provisioner helper
  pods create mode-0777 directories below `/opt/local-path-provisioner` and
  remove their bound volume directory during teardown.
- The namespaced Role can manage helper Pods. The ClusterRole can observe
  Nodes, PVCs, ConfigMaps, Pods and Pod logs, manage PVs, create/patch Events,
  and observe StorageClasses.
- `local-path` is the default StorageClass with `Delete` reclaim policy and
  `WaitForFirstConsumer`. Volumes are node-local, non-replicated, and carry no
  backup or snapshot guarantee. This matches the accepted disposable
  DEV-rebuild-on-loss boundary, not a production storage contract.
- Registry content integrity is pinned by digest, but no image signature or
  publisher authenticity claim is made.

## Not authorized by this checkpoint

- installation or any other cluster mutation;
- retry, rollback, force deletion, finalizer changes, or general cleanup;
- Runtime Binding or Happy Run continuation;
- Platform submission, evidence publication, outage, or failure injection.
