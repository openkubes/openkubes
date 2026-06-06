# CAPI KubeVirt Platform v4.2

Automated deployment of Kubernetes workload clusters on bare metal using [Cluster API](https://cluster-api.sigs.k8s.io/) and [KubeVirt](https://kubevirt.io/).

Each cluster is fully isolated in its **own namespace** — on the management cluster and on the infra cluster.

> 🇩🇪 [Deutsche Version](README_DE.md)

---

## Architecture

```
Host (macOS/Linux)
└── Docker Runner Container
    └── make deploy-full-local
        ├── Create namespace        (Management Cluster: ok1)
        ├── Create infra namespace  (Infra Cluster: ok1)
        ├── Create per-cluster secret (external-infra-kubeconfig-ok1)
        ├── Render + apply manifests
        ├── Fetch workload kubeconfig
        ├── Wait for API server
        ├── Install CNI (Calico / Cilium)
        └── Wait for nodes Ready
```

| Cluster | Role |
|---------|------|
| **Management Cluster** | Hosts CAPI objects (`Cluster`, `KubeadmControlPlane`, `MachineDeployment`, …) |
| **Infra Cluster** | KubeVirt runs VMs as `VirtualMachineInstance`; LoadBalancer service is created here |
| **Workload Cluster** | The newly provisioned Kubernetes cluster running inside the VMs |

---

## Prerequisites

- Docker (for the runner)
- Access to the management cluster (`MGMT_KUBECONFIG`)
- CAPI + CAPK installed on the management cluster
- Secret `external-infra-kubeconfig` present in `capk-system`
- A free MetalLB IP per cluster (`endpoint-ip`)

---

## Quick Start

```bash
# Build the runner image
docker build -t kubernautslabs/capi-platform-runner:v4.2 -f runner/Dockerfile .

# Deploy a cluster
make -C runner deploy-full \
  IMAGE=kubernautslabs/capi-platform-runner:v4.2 \
  KUBECONFIG_HOST=$HOME/.kube/ok-capi-kubevirt-on-kbm.yaml \
  ARGS='country=de provider=kubevirt cluster-name=ok1 cni=calico multus=false endpoint-ip=10.10.10.50'

# Check nodes
KUBECONFIG=rendered/ok1.kubeconfig kubectl get nodes
```

---

## Deploying Two Clusters

```bash
# ok1 → namespace "ok1", LB IP 10.10.10.50
make -C runner deploy-full \
  IMAGE=kubernautslabs/capi-platform-runner:v4.2 \
  KUBECONFIG_HOST=$HOME/.kube/ok-capi-kubevirt-on-kbm.yaml \
  ARGS='country=de provider=kubevirt cluster-name=ok1 cni=calico multus=false endpoint-ip=10.10.10.50'

# ok2 → namespace "ok2", LB IP 10.10.10.51
make -C runner deploy-full \
  IMAGE=kubernautslabs/capi-platform-runner:v4.2 \
  KUBECONFIG_HOST=$HOME/.kube/ok-capi-kubevirt-on-kbm.yaml \
  ARGS='country=de provider=kubevirt cluster-name=ok2 cni=calico multus=false endpoint-ip=10.10.10.51'

# Check status of both clusters
kubectl --kubeconfig $HOME/.kube/ok-capi-kubevirt-on-kbm.yaml get cluster -A
```

> **Without the runner** (requires `kubectl`, `clusterctl`, and `envsubst` installed locally):
> ```bash
> export MGMT_KUBECONFIG=~/.kube/ok-capi-kubevirt-on-kbm.yaml
> make deploy-full country=de provider=kubevirt cluster-name=ok1 cni=calico multus=false endpoint-ip=10.10.10.50
> make deploy-full country=de provider=kubevirt cluster-name=ok2 cni=calico multus=false endpoint-ip=10.10.10.51
> ```

---

## Namespace Isolation

| Resource | Location | Namespace |
|----------|----------|-----------|
| CAPI objects (`Cluster`, `KCP`, `MD` …) | Management Cluster | `<cluster-name>` |
| Per-cluster infra secret | Management Cluster | `<cluster-name>` |
| KubeVirt VMs | Infra Cluster | `<cluster-name>` |
| LoadBalancer Service | Infra Cluster | `<cluster-name>` |

The `external-infra-kubeconfig` secret is automatically copied as `external-infra-kubeconfig-<cluster-name>` with the correct `namespace` key per cluster, so CAPK creates the LB service in the right namespace.

---

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `country` | – | Required. Loads `config/countries/<country>.env` |
| `provider` | – | Required. Loads `config/providers/<provider>.env` |
| `cluster-name` | – | Required. Cluster name and namespace |
| `endpoint-ip` | – | Required. Free MetalLB IP for the control-plane LB |
| `cni` | `calico` | CNI plugin: `calico` or `cilium` |
| `multus` | `false` | Install Multus: `true` or `false` |
| `namespace` | `$(cluster-name)` | Override namespace if needed |
| `kubernetes-version` | `v1.34.1` | Kubernetes version |
| `control-plane-replicas` | `1` | Number of control-plane nodes |
| `worker-replicas` | `2` | Number of worker nodes |

---

## Runner Usage

The runner container avoids Docker-in-Docker and includes all required tools: `kubectl`, `clusterctl`, `helm`, `kustomize`, `yq`, `envsubst`.

```bash
# Interactive shell inside the runner
make -C runner shell \
  IMAGE=kubernautslabs/capi-platform-runner:v4.2 \
  KUBECONFIG_HOST=$HOME/.kube/ok-capi-kubevirt-on-kbm.yaml

# Render only (no deploy)
make -C runner render-cluster \
  IMAGE=kubernautslabs/capi-platform-runner:v4.2 \
  KUBECONFIG_HOST=$HOME/.kube/ok-capi-kubevirt-on-kbm.yaml \
  ARGS='country=de provider=kubevirt cluster-name=ok1 endpoint-ip=10.10.10.50'

# Full deploy
make -C runner deploy-full \
  IMAGE=kubernautslabs/capi-platform-runner:v4.2 \
  KUBECONFIG_HOST=$HOME/.kube/ok-capi-kubevirt-on-kbm.yaml \
  ARGS='country=de provider=kubevirt cluster-name=ok1 cni=calico multus=false endpoint-ip=10.10.10.50'
```

---

## Cleanup

```bash
make -C runner cleanup \
  IMAGE=kubernautslabs/capi-platform-runner:v4.2 \
  KUBECONFIG_HOST=$HOME/.kube/ok-capi-kubevirt-on-kbm.yaml \
  ARGS='country=de provider=kubevirt cluster-name=ok1'
```

Deletes in order:
1. Cluster objects on the management cluster
2. Remaining CAPI objects (best-effort)
3. Per-cluster infra secret (`external-infra-kubeconfig-ok1`)
4. Namespace `ok1` on the management cluster
5. Rendered artifacts (`rendered/ok1.yaml`, `rendered/ok1.kubeconfig`)

---

## Artifacts

After a successful deploy:

```
rendered/ok1.yaml         # rendered CAPI manifests
rendered/ok1.kubeconfig   # kubeconfig of the workload cluster
```

---

## Configuration

### `config/countries/de.env`
Network settings per region: `POD_CIDR`, `SERVICE_CIDR`, `DNS_DOMAIN_SUFFIX`

### `config/providers/kubevirt.env`
Infra provider settings: VM sizes, image URL, secret name, service type.
`CONTROL_PLANE_ENDPOINT_IP` and `KUBEVIRT_VM_NAMESPACE` are set at runtime — **do not hardcode here**.

### `addons/`
- `calico/calico.yaml` — Calico CNI manifest
- `cilium/cilium.yaml` — Cilium CNI manifest (populate via `helm template`)
- `multus/multus.yaml` — Multus manifest (optional)

---

## Notes

- `envsubst` (`gettext-base`) is used for template rendering
- CNI is intentionally installed after API server readiness
- `--validate=false` on CNI apply avoids OpenAPI bootstrap issues
- The runner container is idempotent — re-running `deploy-full` on an existing cluster is safe
