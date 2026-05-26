# OpenKubes Open-RMF Traffic Schedule

The `rmf-traffic-schedule` component is a core orchestration service of the Open-RMF ecosystem running on OpenKubes.

It acts as the central traffic scheduling and negotiation coordination component for ROS 2 robot fleets. The service maintains the global space-time schedule of all participating robots and coordinates traffic negotiations between fleet adapters in real time.

This component is essential for:

- Multi-robot traffic coordination
- Collision avoidance
- Cross-fleet negotiation
- Shared facility navigation
- Real-time route conflict resolution

Within an OpenKubes Robotics architecture, the `rmf-traffic-schedule` service represents a foundational runtime component for scalable industrial autonomous systems.

---

## Architecture Role

The traffic scheduler is conceptually comparable to an air traffic coordination layer for autonomous mobile robots, AMRs, AGVs and industrial robotics systems.

It does not directly control robots.

Instead, it:

- receives traffic intents from fleet adapters
- maintains a global traffic schedule
- negotiates route conflicts
- coordinates crossing priorities
- synchronizes traffic participants over DDS / ROS 2

The scheduler communicates via ROS 2 topics using CycloneDDS middleware.

---

## Repository Structure

```text
platform/
└── robotics/
    └── open-rmf/
        └── rmf-traffic-schedule/
            ├── README.md
            ├── deployment.yaml
            └── kustomization.yaml
```

---

## Kubernetes Deployment

### Deployment Information

| Property | Value |
|---|---|
| Deployment | `rmf-traffic-schedule` |
| Namespace | `rmf` |
| Container | `traffic-schedule` |
| Replicas | `1` |
| ROS Middleware | `CycloneDDS` |
| ROS Domain ID | `15` |

---

## Deployment Manifest

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rmf-traffic-schedule
  namespace: rmf
spec:
  replicas: 1
  selector:
    matchLabels:
      app: rmf-traffic-schedule
  template:
    metadata:
      labels:
        app: rmf-traffic-schedule
    spec:
      containers:
      - name: traffic-schedule
        image: ghcr.io/open-rmf/rmf_deployment_template/rmf-deployment/rmf-sim:latest
        imagePullPolicy: IfNotPresent
        command: ["/bin/bash"]
        args:
        - -c
        - |
          /ros_entrypoint.sh ros2 run rmf_traffic_ros2 rmf_traffic_schedule
        env:
        - name: RMF_USE_SIM_TIME
          value: "true"
        - name: CYCLONEDDS_URI
          value: /etc/cyclonedds/cyclonedds.xml
        - name: ROS_DOMAIN_ID
          value: "15"
        - name: RMW_IMPLEMENTATION
          value: rmw_cyclonedds_cpp
        volumeMounts:
        - mountPath: /etc/cyclonedds
          name: cyclonedds-configmap
      tolerations:
      - effect: NoSchedule
        key: reserved
        operator: Equal
        value: rmf
      volumes:
      - name: cyclonedds-configmap
        configMap:
          name: cyclonedds-configmap
```

---

## Container Runtime

### Base Image

```text
ghcr.io/open-rmf/rmf_deployment_template/rmf-deployment/rmf-sim:latest
```

The simulation image is intentionally reused to prevent ROS 2 dependency and library mismatches between simulation and orchestration components.

---

## ROS 2 Runtime

### Executed Command

```bash
/ros_entrypoint.sh ros2 run rmf_traffic_ros2 rmf_traffic_schedule
```

This launches the Open-RMF traffic scheduling node.

---

## DDS / ROS 2 Configuration

The deployment uses CycloneDDS as ROS 2 middleware.

### Environment Variables

```yaml
- name: RMF_USE_SIM_TIME
  value: "true"

- name: CYCLONEDDS_URI
  value: /etc/cyclonedds/cyclonedds.xml

- name: ROS_DOMAIN_ID
  value: "15"

- name: RMW_IMPLEMENTATION
  value: rmw_cyclonedds_cpp
```

---

## CycloneDDS Configuration

The CycloneDDS configuration is mounted through a Kubernetes ConfigMap.

### Mounted Path

```text
/etc/cyclonedds/cyclonedds.xml
```

### ConfigMap

```text
cyclonedds-configmap
```

This enables centralized DDS network tuning and OpenKubes-specific ROS 2 networking optimization.

---

## OpenKubes Scheduling Requirements

### Node Tolerations

The OpenKubes cluster uses dedicated node taints for robotics and RMF workloads.

Without the following toleration, the pod may remain stuck in a `Pending` state.

```yaml
tolerations:
- effect: NoSchedule
  key: reserved
  operator: Equal
  value: rmf
```

This ensures the workload is scheduled only onto designated RMF-capable worker nodes.

---

## Verification

### Open Container Shell

```bash
kubectl exec -it deploy/rmf-traffic-schedule \
  -n rmf \
  -c traffic-schedule \
  -- /bin/bash
```

### Verify ROS 2 Topics

Inside the container:

```bash
/ros_entrypoint.sh ros2 topic list
```

Expected traffic orchestration topics include:

```text
/rmf_traffic/heartbeat
/rmf_traffic/participants
/rmf_traffic/negotiation_...
```

The presence of these topics confirms:

- successful DDS discovery
- ROS 2 communication
- active traffic negotiation services
- connectivity to simulation and fleet adapters

---

## OpenKubes Robotics Context

This component is part of the broader OpenKubes Robotics architecture.

Related platform components may include:

- Open-RMF Fleet Adapters
- OpenRobOps
- ROS 2 Runtime Services
- DDS Networking
- Multus / SR-IOV Networking
- Observability and Telemetry
- GitOps-based Robotics Lifecycle Management

---

## Future Enhancements

Potential future improvements for OpenKubes Robotics:

- HA deployment of traffic scheduling services
- DDS multicast optimization
- SR-IOV accelerated ROS 2 networking
- OpenTelemetry integration
- KubeVirt-based simulation environments
- GitOps deployment automation
- Sovereign / air-gapped industrial deployments

---

## Related Technologies

- Open-RMF
- ROS 2
- CycloneDDS
- Kubernetes
- OpenKubes
- OpenRobOps
- Multus CNI
- SR-IOV
- KubeVirt

---

## License

Internal OpenKubes Robotics Evaluation / Architecture Documentation.