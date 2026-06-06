# DDS Networking

CycloneDDS configuration for ROS 2 and Open-RMF workloads on OpenKubes.

## make Targets

```sh
make dds-apply     # apply CycloneDDS ConfigMap to the cluster
make dds-verify    # verify ConfigMap and DDS discovery
make dds-clean     # remove DDS ConfigMap
```

## Overview

DDS configuration is mounted as a Kubernetes ConfigMap at `/etc/cyclonedds/cyclonedds.xml`.
OpenKubes optimizes DDS for multi-node Kubernetes environments with Multus CNI for
dedicated network interface attachment.

→ [`../ros2/README.md`](../ros2/README.md) — ROS 2 runtime
→ [`../../networking/multus/README.md`](../../networking/multus/README.md) — Multus CNI
