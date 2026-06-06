# Multus CNI

Multi-network CNI plugin for OpenKubes Robotics and industrial workloads.
Enables attaching multiple network interfaces to pods (DDS, ROS 2, SR-IOV).

## make Targets

```sh
make multus-install    # install Multus
make multus-verify     # check Multus DaemonSet
make multus-clean      # remove Multus
```

## Usage

Enable Multus when deploying a cluster via `capi-platform-v4.2`:

```sh
make -C runner deploy-full \
  IMAGE=kubernautslabs/capi-platform-runner:v4.2 \
  KUBECONFIG_HOST=$HOME/.kube/ok-capi-kubevirt-on-kbm.yaml \
  ARGS='... multus=true ...'
```

→ See also [`../../robotics/dds/README.md`](../../robotics/dds/README.md) for DDS networking.
