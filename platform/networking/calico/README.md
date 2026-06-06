# Calico CNI

Alternative CNI for OpenKubes workload clusters. Default CNI used by `capi-platform-v4.2`.

## make Targets

```sh
make calico-install    # install Calico
make calico-verify     # check Calico pods and node status
make calico-clean      # remove Calico
```

## Configuration

```sh
CALICO_VERSION=v3.28.0
POD_CIDR=192.168.0.0/16    # set in config/countries/<country>.env
```
