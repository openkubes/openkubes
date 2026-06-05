# Cluster API + CAPK Installation

This guide covers installing Cluster API (CAPI) with the KubeVirt Infrastructure
Provider (CAPK) on the Management Cluster, and connecting it to the Infra Cluster.

## Prerequisites

- Management Cluster running (kubeadm on ok-vms)
- KubeVirt installed on Management Cluster
- clusterctl installed (see below)
- Access to the Infra Cluster kubeconfig

## 1. Install clusterctl

curl -L https://github.com/kubernetes-sigs/cluster-api/releases/latest/download/clusterctl-darwin-amd64 \
  -o clusterctl && chmod +x clusterctl && sudo mv clusterctl /usr/local/bin/

## 2. Install cert-manager

kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml
kubectl -n cert-manager wait deployment cert-manager --for=condition=Available --timeout=120s

## 3. Configure clusterctl for CAPK

mkdir -p ~/.cluster-api
cat > ~/.cluster-api/clusterctl.yaml << YAML
providers:
  - name: "kubevirt"
    url: "https://github.com/kubernetes-sigs/cluster-api-provider-kubevirt/releases/download/v0.11.2/infrastructure-components.yaml"
    type: "InfrastructureProvider"
YAML

## 4. Initialize CAPI with CAPK

clusterctl init --infrastructure kubevirt:v0.11.2 -v5
kubectl get pods -n capi-system
kubectl get pods -n capk-system

## 5. Create the Infra Cluster Secret

kubectl -n capk-system create secret generic external-infra-kubeconfig \
  --from-file=kubeconfig=$HOME/.kube/knautic-bare-metal.yaml \
  --from-literal=namespace=capi-workload

kubectl -n capk-system get secret external-infra-kubeconfig \
  -o jsonpath='{.data}' | jq 'keys'
