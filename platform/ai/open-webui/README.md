# Open WebUI

Private chat interface for OpenKubes AI. Connects to the central Ollama
instance and provides a ChatGPT-like experience within your infrastructure.

**Helm Chart:** [open-webui/open-webui](https://helm.openwebui.com/)  
**Version:** v0.10.2 (Chart v15.2.0)

---

## Prerequisites

- Workload cluster running (ok-ai or similar)
- `local-path` StorageClass installed and set as default
- Central Ollama endpoint reachable from the cluster (e.g. `http://<ollama-ip>:11434`) —
  Provider Value; real endpoint lives in `ok-cluster/open-webui/claim-<cluster>.yaml`
- `open-webui` namespace with `pod-security.kubernetes.io/enforce=privileged`

### Install local-path StorageClass (Talos clusters)

Talos clusters do not ship with a StorageClass by default:

```bash
# Install local-path-provisioner
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.30/deploy/local-path-storage.yaml

# Set as default
kubectl patch storageclass local-path \
  -p '{"metadata": {"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'

# Label namespace for privileged pod security (required for local-path on Talos)
kubectl create namespace open-webui
kubectl label namespace open-webui \
  pod-security.kubernetes.io/enforce=privileged
kubectl label namespace local-path-storage \
  pod-security.kubernetes.io/enforce=privileged \
  pod-security.kubernetes.io/warn=privileged \
  pod-security.kubernetes.io/audit=privileged
```

---

## Installation

```bash
helm repo add open-webui https://helm.openwebui.com/
helm repo update open-webui

helm install open-webui open-webui/open-webui \
  --namespace open-webui \
  --create-namespace \
  -f values.yaml
```

After installation, configure the Ollama endpoint:

```bash
kubectl -n open-webui set env statefulset/open-webui \
  OLLAMA_BASE_URL=http://<ollama-ip>:11434 \
  ENABLE_OLLAMA_API=true
```

Or pass it via the Open WebUI UI: Settings → Connections → Ollama API.

---

## Access

```bash
export POD_NAME=$(kubectl get pods -n open-webui \
  -l "app.kubernetes.io/component=open-webui" \
  -o jsonpath="{.items[0].metadata.name}")
kubectl -n open-webui port-forward $POD_NAME 8080:8080
# Open: http://localhost:8080
```

---

## Lessons Learned

- **Talos + local-path:** The `rancher.io/local-path` provisioner requires
  `pod-security.kubernetes.io/enforce=privileged` on both the `local-path-storage`
  and `open-webui` namespaces, because the helper pod uses `hostPath` volumes.
- **OLLAMA_BASE_URL:** The Helm chart's `externalOllama.baseUrl` parameter may
  not override the default correctly. Use `kubectl set env` directly on the
  StatefulSet as a reliable override.
- **StorageClass:** Talos clusters require explicit StorageClass installation.
  local-path uses `WaitForFirstConsumer` binding mode — no node annotation needed.
