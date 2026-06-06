---
apiVersion: infrastructure.cluster.x-k8s.io/v1alpha1
kind: KubevirtCluster
metadata:
  name: ${CLUSTER_NAME}
  namespace: ${NAMESPACE}
spec:
  infraClusterSecretRef:
    apiVersion: v1
    kind: Secret
    name: ${INFRA_CLUSTER_SECRET_NAME}
    namespace: ${INFRA_CLUSTER_SECRET_NAMESPACE}
  controlPlaneServiceTemplate:
    spec:
      type: ${CONTROL_PLANE_SERVICE_TYPE}
