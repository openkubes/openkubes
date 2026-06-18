# KubeVirt Installation

Installs KubeVirt on the **Infra Cluster** (RKE2 bare metal) and the
**Management Cluster** (kubeadm VMs).

## make Targets

```sh
make kubevirt-install       # install KubeVirt + CDI on the current cluster
make kubevirt-install-mgmt  # install KubeVirt on the management cluster
make kubevirt-verify        # check KubeVirt, CDI and virt plugin
make kubevirt-ui            # deploy KubeVirt Manager UI (optional)
make kubevirt-clean         # remove KubeVirt and CDI
```

---

## Overview

```
RKE2 Bare Metal (Infra Cluster)
├── KubeVirt Operator + CR      ← runs VMs
├── CDI (Containerized Data Importer)
├── KubeVirt Manager UI (optional)
└── MetalLB                     ← provides LoadBalancer IPs for VMs

Management Cluster (kubeadm on ok1/ok2/ok3-vm)
└── KubeVirt Operator + CR      ← needed for CAPK to provision workload VMs
```

---

## Manual Steps

<details>
<summary>Step-by-step without make</summary>

### 1. Install KubeVirt on the Infra Cluster

```sh
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.1/kubevirt-operator.yaml
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.1/kubevirt-cr.yaml

kubectl -n kubevirt wait kubevirt kubevirt \
  --for=condition=Available \
  --timeout=300s
```

### 2. Install CDI

```sh
kubectl apply -f https://github.com/kubevirt/containerized-data-importer/releases/latest/download/cdi-operator.yaml
kubectl apply -f https://github.com/kubevirt/containerized-data-importer/releases/latest/download/cdi-cr.yaml

kubectl get pods -n cdi
```

### 3. Install kubectl virt plugin

```sh
kubectl krew install virt
kubectl virt version
```

### 4. Install KubeVirt Manager UI (optional)

```sh
kubectl apply -f https://github.com/kubevirt-manager/kubevirt-manager/releases/download/v1.5.4/bundled-v1.5.4.yaml

# Access via port-forward
kubectl port-forward -n kubevirt-manager svc/kubevirt-manager 8080:8080
# Open: http://localhost:8080
```

### 5. Install KubeVirt on the Management Cluster

```sh
export KUBECONFIG=~/.kube/ok-capi-kubevirt-on-kbm.yaml

kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.1/kubevirt-operator.yaml
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.1/kubevirt-cr.yaml

kubectl -n kubevirt wait kubevirt kubevirt \
  --for=condition=Available \
  --timeout=300s
```

</details>

---

## Verify

```sh
make kubevirt-verify
```

Expected output:

```
# Infra Cluster
NAME       AGE   PHASE   READY
kubevirt   10m   Deployed  True

# CDI
NAME   AGE   PHASE
cdi    10m   Deployed

# Management Cluster
NAME       AGE   PHASE   READY
kubevirt   5m    Deployed  True
```

---

## Next Step

→ [`../../hardware/README.md`](../../hardware/README.md) — Deploy Management VMs

---

## ok-rke2 — Air-Gap Installation (kein Internet auf den Nodes)

`ok-infra` und `ok-gpu` haben keinen direkten IPv4-Internet-Zugang — `ghcr.io` ist
nicht erreichbar. Images müssen manuell über `ok-vpn` (167.233.52.138) transferiert werden.

### KubeVirt + CDI air-gap

```sh
# 1. Manifeste auf ok-vpn herunterladen
ssh root@167.233.52.138 << 'CMDS'
  KUBEVIRT_VERSION=v1.8.1
  CDI_VERSION=v1.60.0

  # Manifeste holen (ok-vpn hat Internet)
  curl -sLO https://github.com/kubevirt/kubevirt/releases/download/${KUBEVIRT_VERSION}/kubevirt-operator.yaml
  curl -sLO https://github.com/kubevirt/kubevirt/releases/download/${KUBEVIRT_VERSION}/kubevirt-cr.yaml
  curl -sLO https://github.com/kubevirt/containerized-data-importer/releases/download/${CDI_VERSION}/cdi-operator.yaml
  curl -sLO https://github.com/kubevirt/containerized-data-importer/releases/download/${CDI_VERSION}/cdi-cr.yaml
CMDS

# 2. Manifeste auf ok-infra kopieren
scp root@167.233.52.138:~/kubevirt-*.yaml root@192.168.100.2:/tmp/
scp root@167.233.52.138:~/cdi-*.yaml      root@192.168.100.2:/tmp/

# 3. Images aus den Manifesten extrahieren und transferieren
# (analog zu ok-rke2/multus/airgap-images.sh — Images via docker pull auf
#  ok-vpn, ctr import auf ok-infra/ok-gpu)

# 4. Auf ok-infra deployen
ssh root@192.168.100.2 'kubectl apply -f /tmp/kubevirt-operator.yaml'
ssh root@192.168.100.2 'kubectl apply -f /tmp/kubevirt-cr.yaml'
ssh root@192.168.100.2 'kubectl apply -f /tmp/cdi-operator.yaml'
ssh root@192.168.100.2 'kubectl apply -f /tmp/cdi-cr.yaml'
```

> **Wichtig für alle air-gap-Deployments:** `imagePullPolicy: IfNotPresent` setzen
> oder als Patch anwenden — sonst versucht containerd den Pull trotz lokalem Image.

→ Vollständige Multus air-gap Installation: [`../../../ok-rke2/multus/README.md`](../../../ok-rke2/multus/README.md)
