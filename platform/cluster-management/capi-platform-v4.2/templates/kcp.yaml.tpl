---
apiVersion: controlplane.cluster.x-k8s.io/v1beta1
kind: KubeadmControlPlane
metadata:
  name: ${CLUSTER_NAME}-control-plane
  namespace: ${NAMESPACE}
spec:
  kubeadmConfigSpec:
    clusterConfiguration:
      controlPlaneEndpoint: "${CONTROL_PLANE_ENDPOINT_IP}:${CONTROL_PLANE_ENDPOINT_PORT}"
      networking:
        dnsDomain: ${CLUSTER_NAME}.${DNS_DOMAIN_SUFFIX}
        podSubnet: ${POD_CIDR}
        serviceSubnet: ${SERVICE_CIDR}
      apiServer:
        certSANs:
          - "${CONTROL_PLANE_ENDPOINT_IP}"
    initConfiguration:
      nodeRegistration:
        criSocket: unix:///run/containerd/containerd.sock
    joinConfiguration:
      nodeRegistration:
        criSocket: unix:///run/containerd/containerd.sock
  machineTemplate:
    infrastructureRef:
      apiVersion: infrastructure.cluster.x-k8s.io/v1alpha1
      kind: KubevirtMachineTemplate
      name: ${CLUSTER_NAME}-control-plane
      namespace: ${NAMESPACE}
  replicas: ${CONTROL_PLANE_REPLICAS}
  version: ${KUBERNETES_VERSION}
