# OpenKubes MVP Upgrade Strategy

For the current MVP, upgrades use a **replace-upgrade** strategy instead of an in-place CAPK rolling upgrade.

## Why

With CAPK v0.11.x we observed recurring upgrade failures where new KubeVirt VMs are created and bootstrap starts, but the Kubernetes Node never registers with the workload API server / ProviderID matching stays pending. This affects both control-plane and worker rolling upgrades.

## Supported MVP behavior

`crossplane-upgrade.sh` now defaults to `Recreate`:

1. Read the live `KubeVirtClusterClaim` for the existing cluster.
2. Patch the claim to the target Kubernetes version.
3. Cleanly delete the existing CAPI/CAPK workload cluster resources.
4. Recreate the workload cluster with the same name, endpoint IP, CNI, Multus setting and replica counts.
5. Verify the real workload nodes with `kubectl get nodes` and require all nodes to report the target kubelet version.

This is not a zero-downtime upgrade. It is intended to make the MVP reliable while CAPK rolling upgrades are evaluated separately.

## Experimental rolling path

The previous rolling implementation is kept as:

```bash
scripts/crossplane-upgrade-rolling.sh
```

It is disabled by default. To test it explicitly:

```bash
UPGRADE_STRATEGY=RollingUpdate OPENKUBES_ENABLE_EXPERIMENTAL_ROLLING=true /workspace/scripts/crossplane-upgrade.sh
```

## Usage

```bash
make upgrade cluster=ok1 kubernetes-version=v1.34.1
make kubeconfig cluster=ok1
KUBECONFIG=~/.kube/ok1.kubeconfig kubectl get nodes -o wide
```

The upgrade is only successful when all workload nodes report the target kubelet version.
