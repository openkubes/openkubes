# OK-141 delete-test preparation v1

Status: **OFFLINE-PREPARED / BLOCKED / NO-GO**

This checkpoint prepares the first controlled deletion proof for the healthy
`disposable-ok141` cluster. It contains no live UID, resource version, endpoint,
credential or deletion authority. No stage is enabled.

The intended ownership flow is:

```text
freeze fresh private identities
        ↓
remove three finalizer-free Argo Applications
        ↓
remove Argo registration and exclusive AppProject
        ↓
delete HelmChartProxy; let CAAPH close HelmReleaseProxy
        ↓
delete only CAPI Cluster; let CAPI/CAPK/KubeVirt close the runtime graph
        ↓
prove VM/VMI/DataVolume/PVC absence
        ↓
clean exact provider prerequisites and two Retain-policy disk graphs
        ↓
remove privileged provider-access Secret last
        ↓
remove management Namespace and prove terminal absence
```

## Read-only findings

- The CAPI Cluster is `Provisioned`, `Available=True` and not deleting.
- The three Argo Applications are `Synced`, `Healthy`, automated and have no
  deletion finalizer. Removing them therefore does not request target-resource
  deletion.
- CAAPH owns one HelmChartProxy and one generated HelmReleaseProxy. Their native
  finalizers must complete while the workload API is still reachable.
- CAPK/KubeVirt own two Machines, VMs, VMIs, DataVolumes and provider PVCs.
  These objects must never be directly deleted by the bounded executor.
- The four platform PVs inside the disposable cluster use `Delete` reclaim
  semantics and disappear with the workload runtime.
- The two VM-disk PVs on `ok-infra` use `Retain`. Their exact PV and Longhorn
  Volume identities therefore require a separate, destructive post-CAPI cleanup
  gate after both volumes are `Released` and `detached`.
- Shared `ok147-*` runner, ledger and admission objects are reusable execution
  infrastructure, not disposable-cluster state, and remain out of scope.

## Why this is not an OpenKubes reconciler

OpenKubes sequences bounded actions and evaluates evidence. Argo, CAAPH,
CAPI/CAPK, KubeVirt and Longhorn retain their existing ownership. If any native
finalizer or controller-owned cleanup stalls, the protocol stops; it does not
repair the owning controller, strip finalizers or directly delete its children.

## Verification

```bash
python3 architecture/spikes/ADR-Platform-030/delete-test-v1/verify_delete_test_v1.py \
  --protocol architecture/spikes/ADR-Platform-030/delete-test-v1/delete-test-protocol-v1.yaml \
  --observation architecture/spikes/ADR-Platform-030/delete-test-v1/delete-test-read-only-observation-v1.yaml \
  --publication-candidate architecture/spikes/ADR-Platform-030/delete-test-v1/delete-test-preparation-publication-candidate-v1.yaml

python3 architecture/spikes/ADR-Platform-030/delete-test-v1/test_delete_test_v1.py -v
```

Expected result:

```text
PASS-DELETE-PREPARATION-OFFLINE-NO-GO
```

A later execution requires a fresh private ten-minute UID/resourceVersion
binding plus explicit destructive authorization for each mutating boundary.
This checkpoint grants none of them.
