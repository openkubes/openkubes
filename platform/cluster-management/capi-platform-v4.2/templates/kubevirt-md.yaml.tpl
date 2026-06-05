---
apiVersion: infrastructure.cluster.x-k8s.io/v1alpha1
kind: KubevirtMachineTemplate
metadata:
  name: ${CLUSTER_NAME}-md-0
  namespace: ${NAMESPACE}
spec:
  template:
    spec:
      virtualMachineBootstrapCheck:
        checkStrategy: ssh
      virtualMachineTemplate:
        metadata:
          namespace: ${KUBEVIRT_VM_NAMESPACE}
        spec:
          runStrategy: Always
          template:
            spec:
              domain:
                cpu:
                  cores: ${WORKER_CPU_CORES}
                devices:
                  disks:
                    - disk:
                        bus: virtio
                      name: containervolume
                  networkInterfaceMultiqueue: true
                memory:
                  guest: ${WORKER_MEMORY}
              evictionStrategy: External
              volumes:
                - containerDisk:
                    image: ${VM_IMAGE_URL}
                  name: containervolume
---
apiVersion: bootstrap.cluster.x-k8s.io/v1beta1
kind: KubeadmConfigTemplate
metadata:
  name: ${CLUSTER_NAME}-md-0
  namespace: ${NAMESPACE}
spec:
  template:
    spec:
      joinConfiguration:
        nodeRegistration:
          criSocket: unix:///run/containerd/containerd.sock
---
apiVersion: cluster.x-k8s.io/v1beta1
kind: MachineDeployment
metadata:
  name: ${CLUSTER_NAME}-md-0
  namespace: ${NAMESPACE}
spec:
  clusterName: ${CLUSTER_NAME}
  replicas: ${WORKER_REPLICAS}
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
  selector:
    matchLabels:
      cluster.x-k8s.io/cluster-name: ${CLUSTER_NAME}
      nodepool: md-0
  template:
    metadata:
      labels:
        cluster.x-k8s.io/cluster-name: ${CLUSTER_NAME}
        nodepool: md-0
    spec:
      clusterName: ${CLUSTER_NAME}
      version: ${KUBERNETES_VERSION}
      bootstrap:
        configRef:
          apiVersion: bootstrap.cluster.x-k8s.io/v1beta1
          kind: KubeadmConfigTemplate
          name: ${CLUSTER_NAME}-md-0
          namespace: ${NAMESPACE}
      infrastructureRef:
        apiVersion: infrastructure.cluster.x-k8s.io/v1alpha1
        kind: KubevirtMachineTemplate
        name: ${CLUSTER_NAME}-md-0
        namespace: ${NAMESPACE}
