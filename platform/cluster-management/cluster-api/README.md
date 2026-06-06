# Cluster API + CAPK

Installs Cluster API (CAPI) with the KubeVirt Infrastructure Provider (CAPK)
on the Management Cluster and connects it to the Infra Cluster.

## make Targets

```sh
make capi-install    # install clusterctl, cert-manager, configure and init CAPI + CAPK
make capi-verify     # check pods in capi-system and capk-system
make capi-secret     # create external-infra-kubeconfig secret in capk-system
make capi-clean      # remove CAPI + CAPK from the management cluster
```

## Prerequisites

- Management Cluster running (kubeadm on ok-vms)
- KubeVirt installed on Management Cluster → [`../virtualization/kubevirt/README.md`](../../virtualization/kubevirt/README.md)
- Access to the Infra Cluster kubeconfig

---

## Manual Steps

<details>
<summary>Step-by-step without make</summary>

### 1. Install clusterctl

```sh
curl -L https://github.com/kubernetes-sigs/cluster-api/releases/latest/download/clusterctl-linux-amd64 \
  -o clusterctl && chmod +x clusterctl && sudo mv clusterctl /usr/local/bin/
```

### 2. Install cert-manager

```sh
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml
kubectl -n cert-manager wait deployment cert-manager --for=condition=Available --timeout=120s
```

### 3. Configure clusterctl for CAPK

```sh
mkdir -p ~/.cluster-api
cat > ~/.cluster-api/clusterctl.yaml << YAML
providers:
  - name: "kubevirt"
    url: "https://github.com/kubernetes-sigs/cluster-api-provider-kubevirt/releases/download/v0.11.2/infrastructure-components.yaml"
    type: "InfrastructureProvider"
YAML
```

### 4. Initialize CAPI with CAPK

```sh
clusterctl init --infrastructure kubevirt:v0.11.2 -v5
kubectl get pods -n capi-system
kubectl get pods -n capk-system
```

### 5. Create the Infra Cluster Secret

```sh
kubectl -n capk-system create secret generic external-infra-kubeconfig \
  --from-file=kubeconfig=$HOME/.kube/knautic-bare-metal.yaml \
  --from-literal=namespace=capi-workload

kubectl -n capk-system get secret external-infra-kubeconfig \
  -o jsonpath='{.data}' | jq 'keys'
```

</details>

---

## Next Step

→ [`../crossplane/README.md`](../crossplane/README.md) — Deploy workload clusters via Crossplane
