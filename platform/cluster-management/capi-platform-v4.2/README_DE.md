# CAPI KubeVirt Platform v4.2

Automatisiertes Deployment von Kubernetes Workload-Clustern auf Bare Metal mit [Cluster API](https://cluster-api.sigs.k8s.io/) und [KubeVirt](https://kubevirt.io/).

Jeder Cluster wird vollständig isoliert in seinem **eigenen Namespace** deployed – auf dem Management-Cluster und auf dem Infra-Cluster.

> 🇬🇧 [English Version](README.md)

---

## Architektur

```
Host (macOS/Linux)
└── Docker Runner Container
    └── make deploy-full-local
        ├── Namespace anlegen        (Management-Cluster: ok1)
        ├── Infra-Namespace anlegen  (Infra-Cluster: ok1)
        ├── Per-Cluster Secret anlegen (external-infra-kubeconfig-ok1)
        ├── Manifeste rendern + apply
        ├── Workload-Kubeconfig holen
        ├── API-Server warten
        ├── CNI installieren (Calico / Cilium)
        └── Nodes warten
```

| Cluster | Rolle |
|---------|-------|
| **Management-Cluster** | Hostet CAPI-Objekte (`Cluster`, `KubeadmControlPlane`, `MachineDeployment` …) |
| **Infra-Cluster** | KubeVirt startet VMs als `VirtualMachineInstance`; LoadBalancer-Service wird hier angelegt |
| **Workload-Cluster** | Der neu provisionierte Kubernetes-Cluster innerhalb der VMs |

---

## Voraussetzungen

- Docker (für den Runner)
- Zugang zum Management-Cluster (`MGMT_KUBECONFIG`)
- CAPI + CAPK auf dem Management-Cluster installiert
- Secret `external-infra-kubeconfig` in `capk-system` vorhanden
- Freie MetalLB-IP pro Cluster (`endpoint-ip`)

---

## Quick Start

```bash
# Runner bauen
docker build -t openkubes/capi-platform-runner:v4.2 -f runner/Dockerfile .

# Cluster deployen
make -C runner deploy-full \
  IMAGE=openkubes/capi-platform-runner:v4.2 \
  KUBECONFIG_HOST=$HOME/.kube/ok-capi-kubevirt-on-kbm.yaml \
  ARGS='country=de provider=kubevirt cluster-name=ok1 cni=calico multus=false endpoint-ip=10.10.10.50'

# Nodes prüfen
KUBECONFIG=rendered/ok1.kubeconfig kubectl get nodes
```

---

## Zwei Cluster deployen

```bash
# ok1 → Namespace "ok1", LB-IP 10.10.10.50
make -C runner deploy-full \
  IMAGE=openkubes/capi-platform-runner:v4.2 \
  KUBECONFIG_HOST=$HOME/.kube/ok-capi-kubevirt-on-kbm.yaml \
  ARGS='country=de provider=kubevirt cluster-name=ok1 cni=calico multus=false endpoint-ip=10.10.10.50'

# ok2 → Namespace "ok2", LB-IP 10.10.10.51
make -C runner deploy-full \
  IMAGE=openkubes/capi-platform-runner:v4.2 \
  KUBECONFIG_HOST=$HOME/.kube/ok-capi-kubevirt-on-kbm.yaml \
  ARGS='country=de provider=kubevirt cluster-name=ok2 cni=calico multus=false endpoint-ip=10.10.10.51'

# Status beider Cluster
kubectl --kubeconfig $HOME/.kube/ok-capi-kubevirt-on-kbm.yaml get cluster -A
```

> **Ohne Runner** (wenn `kubectl`, `clusterctl` und `envsubst` lokal installiert sind):
> ```bash
> export MGMT_KUBECONFIG=~/.kube/ok-capi-kubevirt-on-kbm.yaml
> make deploy-full country=de provider=kubevirt cluster-name=ok1 cni=calico multus=false endpoint-ip=10.10.10.50
> make deploy-full country=de provider=kubevirt cluster-name=ok2 cni=calico multus=false endpoint-ip=10.10.10.51
> ```

---

## Namespace-Isolation

| Ressource | Ort | Namespace |
|-----------|-----|-----------|
| CAPI-Objekte (`Cluster`, `KCP`, `MD` …) | Management-Cluster | `<cluster-name>` |
| Per-Cluster Infra-Secret | Management-Cluster | `<cluster-name>` |
| KubeVirt VMs | Infra-Cluster | `<cluster-name>` |
| LoadBalancer Service | Infra-Cluster | `<cluster-name>` |

Das `external-infra-kubeconfig` Secret wird automatisch als `external-infra-kubeconfig-<cluster-name>` mit dem korrekten `namespace`-Key pro Cluster kopiert. So legt CAPK den LB-Service im richtigen Namespace an.

---

## Parameter

| Parameter | Default | Beschreibung |
|-----------|---------|--------------|
| `country` | – | Pflicht. Config aus `config/countries/<country>.env` |
| `provider` | – | Pflicht. Config aus `config/providers/<provider>.env` |
| `cluster-name` | – | Pflicht. Name des Clusters und Namespace |
| `endpoint-ip` | – | Pflicht. Freie MetalLB-IP für den Control-Plane LB |
| `cni` | `calico` | CNI-Plugin: `calico` oder `cilium` |
| `multus` | `false` | Multus installieren: `true` oder `false` |
| `namespace` | `$(cluster-name)` | Namespace überschreiben falls gewünscht |
| `kubernetes-version` | `v1.34.1` | Kubernetes-Version |
| `control-plane-replicas` | `1` | Anzahl Control-Plane Nodes |
| `worker-replicas` | `2` | Anzahl Worker Nodes |

---

## Runner Nutzung

Der Runner-Container vermeidet Docker-in-Docker und enthält alle nötigen Tools: `kubectl`, `clusterctl`, `helm`, `kustomize`, `yq`, `envsubst`.

```bash
# Interaktive Shell im Runner
make -C runner shell \
  IMAGE=openkubes/capi-platform-runner:v4.2 \
  KUBECONFIG_HOST=$HOME/.kube/ok-capi-kubevirt-on-kbm.yaml

# Nur rendern (kein Deploy)
make -C runner render-cluster \
  IMAGE=openkubes/capi-platform-runner:v4.2 \
  KUBECONFIG_HOST=$HOME/.kube/ok-capi-kubevirt-on-kbm.yaml \
  ARGS='country=de provider=kubevirt cluster-name=ok1 endpoint-ip=10.10.10.50'

# Vollständiger Deploy
make -C runner deploy-full \
  IMAGE=openkubes/capi-platform-runner:v4.2 \
  KUBECONFIG_HOST=$HOME/.kube/ok-capi-kubevirt-on-kbm.yaml \
  ARGS='country=de provider=kubevirt cluster-name=ok1 cni=calico multus=false endpoint-ip=10.10.10.50'
```

---

## Cleanup

```bash
make -C runner cleanup \
  IMAGE=openkubes/capi-platform-runner:v4.2 \
  KUBECONFIG_HOST=$HOME/.kube/ok-capi-kubevirt-on-kbm.yaml \
  ARGS='country=de provider=kubevirt cluster-name=ok1'
```

Löscht in dieser Reihenfolge:
1. Cluster-Objekte auf dem Management-Cluster
2. Verbleibende CAPI-Objekte (best-effort)
3. Per-Cluster Infra-Secret (`external-infra-kubeconfig-ok1`)
4. Namespace `ok1` auf dem Management-Cluster
5. Rendered-Artefakte (`rendered/ok1.yaml`, `rendered/ok1.kubeconfig`)

---

## Artefakte

Nach erfolgreichem Deploy:

```
rendered/ok1.yaml         # gerenderte CAPI-Manifeste
rendered/ok1.kubeconfig   # Kubeconfig des Workload-Clusters
```

---

## Konfiguration

### `config/countries/de.env`
Netzwerk-Einstellungen pro Region: `POD_CIDR`, `SERVICE_CIDR`, `DNS_DOMAIN_SUFFIX`

### `config/providers/kubevirt.env`
Infra-Provider-Einstellungen: VM-Größen, Image-URL, Secret-Name, Service-Typ.
`CONTROL_PLANE_ENDPOINT_IP` und `KUBEVIRT_VM_NAMESPACE` werden zur Laufzeit gesetzt – **nicht hier einchecken**.

### `addons/`
- `calico/calico.yaml` – Calico CNI Manifest
- `cilium/cilium.yaml` – Cilium CNI Manifest (per `helm template` befüllen)
- `multus/multus.yaml` – Multus Manifest (optional)

---

## Hinweise

- `envsubst` (`gettext-base`) wird für das Template-Rendering verwendet
- CNI wird bewusst erst nach API-Server-Readiness installiert
- `--validate=false` beim CNI-Apply verhindert OpenAPI-Bootstrap-Probleme
- Der Runner-Container ist idempotent – erneutes `deploy-full` auf einem bestehenden Cluster ist sicher
