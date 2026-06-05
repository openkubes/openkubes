---
apiVersion: cluster.x-k8s.io/v1beta1
kind: Cluster
metadata:
  name: ${CLUSTER_NAME}
  namespace: ${NAMESPACE}
spec:
  clusterNetwork:
    pods:
      cidrBlocks:
        - ${POD_CIDR}
    services:
      cidrBlocks:
        - ${SERVICE_CIDR}
  controlPlaneRef:
    apiVersion: controlplane.cluster.x-k8s.io/v1beta1
    kind: KubeadmControlPlane
    name: ${CLUSTER_NAME}-control-plane
    namespace: ${NAMESPACE}
  infrastructureRef:
    apiVersion: infrastructure.cluster.x-k8s.io/v1alpha1
    kind: KubevirtCluster
    name: ${CLUSTER_NAME}
    namespace: ${NAMESPACE}
