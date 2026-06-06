# Cilium CNI

Default CNI for OpenKubes. Provides eBPF-based networking, network policy and observability.

## make Targets

```sh
make cilium-install    # install Cilium via Helm
make cilium-verify     # check Cilium pods and connectivity
make cilium-clean      # remove Cilium
```

## Configuration

Cilium is configured via `.env`:

```sh
CILIUM_VERSION=1.16.0
CILIUM_NAMESPACE=kube-system
```

> For Robotics / industrial multi-network setups, use Multus CNI alongside Cilium.
> → [`../multus/README.md`](../multus/README.md)
