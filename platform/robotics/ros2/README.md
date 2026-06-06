# ROS 2 on Kubernetes

Runs ROS 2 workloads on OpenKubes with CycloneDDS middleware.

## make Targets

```sh
make ros2-deploy     # deploy ROS 2 runtime components
make ros2-verify     # check pods and ROS 2 topic discovery
make ros2-clean      # remove ROS 2 components
```

## Prerequisites

- Multus CNI installed → [`../../networking/multus/README.md`](../../networking/multus/README.md)
- DDS network configured → [`../dds/README.md`](../dds/README.md)
- Nodes tainted with `reserved=rmf:NoSchedule` for dedicated scheduling

## Key Environment Variables

```sh
ROS_DOMAIN_ID=15
RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
CYCLONEDDS_URI=/etc/cyclonedds/cyclonedds.xml
```
