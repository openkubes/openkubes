# OpenKubes AI Platform

**Private GPT. On-Prem. Sovereign.**

Run your own AI — no cloud, no data leakage, no vendor lock-in.
OpenKubes AI lets teams claim a dedicated Open WebUI instance when they need
one, powered by a shared GPU backend, deployed with a single `kubectl apply`.
Agent backends may also register with a shared Open WebUI instance instead of
claiming their own (see ADR-Platform-015 Addendum).

---

## What it does

```bash
kubectl apply -f openwebuiclaim.yaml
# Open WebUI running on your Kubernetes cluster in ~90 seconds
```

Behind the scenes:

```
ok-mgmt (Management Cluster)
└── Crossplane + OpenWebUIClaim
    └── Helm Release → Open WebUI on ok-ai

ok-gpu (RTX 4000 Ada, 20GB VRAM)
└── Ollama → mistral, llama3, codellama
```

One GPU. Many teams. Claim your own chat UI, or register your agent backend
into a shared one.

---

## Architecture

```
ok-mgmt (Management Cluster, Talos, ok-infra)
└── Crossplane
    └── OpenWebUIClaim → Helm Release → Open WebUI

ok-ai (Workload Cluster, Talos, ok-gpu)
└── Open WebUI → Ollama API (internal)

ok-gpu (RKE2, RTX 4000 Ada)
└── Ollama → mistral / llama3 / codellama
```

**OpenKubes owns the contracts. The ecosystem provides the implementations.**
Swap Ollama for vLLM without touching the `OpenWebUIClaim`. Agent backends
remain replaceable behind the Agent Interface Contract (ADR-015). Open WebUI
is currently the selected frontend; frontend substitutability has not yet
been formalized as a platform contract.

---

## Getting started

### Prerequisites

- ok-mgmt with Crossplane + OpenWebUI XRD — run `bootstrap-mgmt.sh.tpl` (8 steps, ~2 min)
- Workload cluster with local-path StorageClass: `make install-storage CLUSTER=ok-ai`
- Ollama with GPU: `make -C ok-rke2/ai-services install && make pull`

### Deploy Open WebUI

```bash
# Add your cluster to ok-mgmt
kubectl --kubeconfig ~/.kube/ok-mgmt.yaml \
  create secret generic ok-ai-kubeconfig \
  -n crossplane-system \
  --from-file=kubeconfig=~/.kube/ok-ai.yaml

# Submit the claim — that's all
kubectl --kubeconfig ~/.kube/ok-mgmt.yaml \
  apply -f open-webui/crossplane/examples/ok-ai.yaml

# Watch it deploy (~90 seconds)
kubectl --kubeconfig ~/.kube/ok-mgmt.yaml \
  get openwebuiclaim -n openkubes-system -w
```

### The claim

```yaml
apiVersion: platform.openkubes.ai/v1alpha1
kind: OpenWebUIClaim
metadata:
  name: my-team
  namespace: openkubes-system
spec:
  clusterRef: ok-ai
  ollamaEndpoint: http://OLLAMA_IP:11434   # Provider Value — replace
  namespace: open-webui
```

---

## Models

| Model | Size | Use Case |
|---|---|---|
| mistral | 7.2B, 4.1GB | General purpose, fast |
| llama3 | 8B, ~4.7GB | Strong reasoning |
| codellama | 7B, ~3.8GB | Code generation |

```bash
make -C ok-rke2/ai-services pull MODELS="mistral llama3 codellama"
```

---

## Roadmap

| Feature | Status |
|---|---|
| Ollama with GPU on RKE2 | done |
| Open WebUI via Crossplane Claim | done |
| MCP Connectors (Jira, Confluence) | planned |
| RAG over internal docs | planned |
| OllamaModelClaim self-service | planned |

---

## Why OpenKubes AI?

Most private AI setups are scripts. OpenKubes AI is a platform:

- **Declarative** — kubectl apply creates everything, kubectl delete tears it down
- **Self-service** — teams claim their own AI without involving ops
- **Sovereign** — runs entirely on your hardware, your network, your rules
- **Extensible** — swap models or agent backends without changing the contract

> OpenKubes owns the contracts, not the components.

---

## Links

- [ADR-Platform-005: Shared AI Services](../../architecture/decisions/ADR-Platform-005-shared-ai-services.md)
- [Kubernauts OpenKubes AI](https://kubernauts.de/de/openkubes/openkubes-ai/)
- [OpenKubes Platform](https://github.com/openkubes/openkubes)
