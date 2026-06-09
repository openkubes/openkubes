# OpenKubesCluster – Cluster Management

Self-service Kubernetes cluster lifecycle management via Crossplane + Cluster API.

---

## Quick Start — Zero to Production in 5 Commands

```bash
cd platform/cluster-management

make deploy         cluster=ok1   # ~2 min  → Kubernetes cluster
make kubeconfig     cluster=ok1   # ~5 sec  → kubeconfig saved
make manager-deploy cluster=ok1   # ~30 sec → Headlamp UI on CP node
make ingress-setup  cluster=ok1   # ~30 sec → Traefik + INFRA LB
make cert-setup     cluster=ok1   # ~90 sec → cert-manager + Let's Encrypt
```

Result: `https://headlamp.openkubes.ai` → **HTTP/2 200 OK** with valid TLS certificate 🎉

---

## Prerequisites

| Requirement | Notes |
|---|---|
| kubectl | configured for management cluster |
| helm | ≥ 3.14 |
| clusterctl | for kubeconfig retrieval |
| Crossplane | installed on management cluster |
| CAPI + CAPK | installed on management cluster |
| DNS A-Record | e.g. `headlamp.openkubes.ai → <LB_IP>` for TLS |

---

## Cluster Lifecycle

### Deploy

```bash
make deploy cluster=ok1
```

Applies `crossplane/examples/ok1.yaml` and waits for the deploy Job to complete (~2 min).

### Delete

```bash
make delete cluster=ok1
```

Cleanly removes the cluster via a Cleanup Job — VMs, namespaces, secrets.

### Kubeconfig

```bash
make kubeconfig cluster=ok1
# Saved to ~/.kube/ok1.kubeconfig

KUBECONFIG=~/.kube/ok1.kubeconfig kubectl get nodes
```

### Status

```bash
make status cluster=ok1
```

### Logs

```bash
make logs cluster=ok1
```

---

## Cluster Upgrade

### Recreate (reliable, supported)

Deletes and recreates the cluster with the target version. Workloads will be lost.

```bash
make recreate cluster=ok1 kubernetes-version=v1.34.1
```

### Rolling Upgrade (experimental)

⚠️ Requires CAPK v0.12+ for reliable ProviderID registration.
With CAPK v0.11.x this may hang. Use `make recreate` instead.

```bash
make upgrade cluster=ok1 kubernetes-version=v1.34.1
```

See [`capi-platform-v4.2/UPGRADE_MVP.md`](./capi-platform-v4.2/UPGRADE_MVP.md) for details.

---

## Cluster Manager (Headlamp)

[Headlamp](https://headlamp.dev) — CNCF Sandbox, official Kubernetes Dashboard successor.
Automatically deployed on the control-plane node for INFRA LB compatibility.

```bash
make manager-deploy  cluster=ok1   # install (auto nodeSelector: control-plane)
make manager-token   cluster=ok1   # generate admin token (valid 24h)
make manager-open    cluster=ok1   # port-forward + open http://localhost:8080
make manager-status  cluster=ok1   # show pod + service status
make manager-delete  cluster=ok1   # remove Headlamp
```

---

## Ingress (Traefik)

Traefik is deployed as a NodePort service on the control-plane node.
Traffic is routed via the INFRA MetalLB LoadBalancer (`cluster-lb`) — no MetalLB needed on the workload cluster.

```
Internet → INFRA MetalLB (84.200.100.228)
         → ok1-lb Service (NodePort)
         → Traefik (control-plane node)
         → Headlamp / other services
```

```bash
make ingress-setup   cluster=ok1   # deploy Traefik + patch INFRA LB
make ingress-status  cluster=ok1   # show Traefik + LB status
make ingress-delete  cluster=ok1   # remove Traefik only
make ingress-delete  cluster=ok1 cert=true   # remove Traefik + cert-manager
```

### How ingress-setup works

1. Creates `ok1-kubeconfig` Secret in `crossplane-system`
2. Creates `ok1-helm` + `ok1-kubernetes` ProviderConfigs
3. Deploys Traefik via Crossplane Helm Release (NodePort, CP node)
4. Waits for Traefik `Ready`
5. Reads INFRA kubeconfig from `external-infra-kubeconfig` secret in `capk-system`
6. Patches `ok1-lb` INFRA Service to expose ports 80/443

---

## TLS / cert-manager

cert-manager with Let's Encrypt HTTP-01 challenge.
The ACME solver pod runs on the control-plane node (via `podTemplate`) for INFRA LB routing.

```bash
make cert-setup   cluster=ok1   # deploy cert-manager + ClusterIssuers + Ingress
make cert-status  cluster=ok1   # show certificate status
make cert-delete  cluster=ok1   # remove cert-manager
```

### Prerequisites for TLS

1. DNS A-Record pointing to the INFRA LB IP:
   ```
   headlamp.openkubes.ai → 84.200.100.228
   ```
2. `crossplane/examples/ok1-certmanager.yaml` with correct email + domain

### How cert-setup works

1. Deploys cert-manager v1.17.2 via Crossplane Helm Release
2. Creates `letsencrypt-staging` and `letsencrypt-prod` ClusterIssuers
3. Creates Headlamp Ingress with TLS annotation
4. Waits for cert-manager `Ready`
5. Waits for certificate `Ready=True`

---

## Full Lifecycle Test (Delete + Recreate)

Tested end-to-end — complete stack from zero to production:

```bash
# 1. Delete everything
make ingress-delete cluster=ok1 cert=true   # remove Traefik + cert-manager
make delete         cluster=ok1             # delete workload cluster

# 2. Recreate
make deploy         cluster=ok1             # ~2 min
make kubeconfig     cluster=ok1             # ~5 sec
make manager-deploy cluster=ok1             # ~30 sec (auto CP node)
make ingress-setup  cluster=ok1             # ~30 sec
make cert-setup     cluster=ok1             # ~90 sec

# 3. Verify
curl -I https://headlamp.openkubes.ai
# → HTTP/2 200 ✅
```

Total time from zero to `https://headlamp.openkubes.ai`: **~4 minutes** 🚀

---

## Cluster Claim Example

```yaml
# crossplane/examples/ok1.yaml
apiVersion: platform.openkubes.ai/v1alpha1
kind: KubeVirtClusterClaim
metadata:
  name: ok1
  namespace: openkubes-system
spec:
  country: de
  provider: kubevirt
  endpointIP: 84.200.100.228
  cni: calico
  multus: "false"
  controlPlane:
    replicas: 1
    kubernetesVersion: v1.34.1
  workers:
    replicas: 1
  runnerImage: kubernautslabs/capi-platform-runner:v4.2
```

---

## All Make Targets

| Target | Description |
|---|---|
| `make setup` | One-time: apply XRDs, Compositions, RBAC |
| `make deploy cluster=ok1` | Deploy a workload cluster |
| `make delete cluster=ok1` | Clean delete via Cleanup Job |
| `make kubeconfig cluster=ok1` | Retrieve workload cluster kubeconfig |
| `make recreate cluster=ok1 kubernetes-version=v1.34.1` | Reliable upgrade via recreate |
| `make upgrade cluster=ok1 kubernetes-version=v1.34.1` | Rolling upgrade (experimental) |
| `make status cluster=ok1` | Show cluster status |
| `make logs cluster=ok1` | Follow deploy Job logs |
| `make check cluster=ok1` | Check for leftover resources |
| `make force-clean cluster=ok1` | Emergency cleanup |
| `make manager-deploy cluster=ok1` | Install Headlamp on CP node |
| `make manager-token cluster=ok1` | Generate Headlamp admin token (24h) |
| `make manager-open cluster=ok1` | Port-forward + open browser |
| `make manager-status cluster=ok1` | Show Headlamp status |
| `make manager-delete cluster=ok1` | Remove Headlamp |
| `make ingress-setup cluster=ok1` | Deploy Traefik + patch INFRA LB |
| `make ingress-delete cluster=ok1` | Remove Traefik |
| `make ingress-delete cluster=ok1 cert=true` | Remove Traefik + cert-manager |
| `make ingress-status cluster=ok1` | Show Traefik + LB status |
| `make cert-setup cluster=ok1` | Deploy cert-manager + Let's Encrypt |
| `make cert-delete cluster=ok1` | Remove cert-manager |
| `make cert-status cluster=ok1` | Show certificate status |

---

## Architecture Notes

### Why no MetalLB on workload cluster?

MetalLB L2 does not work reliably on nested KubeVirt VMs because ARP broadcasts
cannot reach the physical network. Instead, the INFRA MetalLB acts as a proxy:

```
INFRA MetalLB Pool: 84.200.100.224-84.200.100.240
ok1-lb Service:     84.200.100.228 → CP Node NodePorts
```

### Why control-plane node for Traefik and Headlamp?

The `ok1-lb` INFRA Service selector targets only `role: control-plane` nodes.
All workload-facing services (Traefik, Headlamp, ACME solver) must run on the
CP node to receive traffic from the INFRA LB.

---

## References

- [Crossplane](https://crossplane.io)
- [Cluster API](https://cluster-api.sigs.k8s.io)
- [CAPK (KubeVirt Provider)](https://github.com/kubernetes-sigs/cluster-api-provider-kubevirt)
- [Headlamp](https://headlamp.dev)
- [Traefik](https://traefik.io)
- [cert-manager](https://cert-manager.io)
- Related: [`platform/virtualization/openkubesvm/`](../virtualization/openkubesvm/README.md)
