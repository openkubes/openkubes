---
apiVersion: infrastructure.cluster.x-k8s.io/v1alpha1
kind: KubevirtMachineTemplate
metadata:
  name: ${CLUSTER_NAME}-control-plane
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
                  cores: ${CONTROL_PLANE_CPU_CORES}
                devices:
                  disks:
                    - disk:
                        bus: virtio
                      name: containervolume
                  networkInterfaceMultiqueue: true
                memory:
                  guest: ${CONTROL_PLANE_MEMORY}
              evictionStrategy: External
              volumes:
                - containerDisk:
                    image: ${VM_IMAGE_URL}
                  name: containervolume
