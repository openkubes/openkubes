# OpenKubes AI Platform

The AI layer of the OpenKubes platform. Provides private, sovereign AI services
for all workload clusters — no data leaves your infrastructure.

> **OpenKubes AI = AI On-Prem, done right.**
> LLM inference, private chat, MCP connectors for Jira/Confluence, and more.

---

## Vision

OpenKubes AI is a curated, self-hosted AI platform built on top of OpenKubes.
It enables teams to run LLMs locally, connect them to their knowledge base
(Confluence, Jira, Git), and build AI-powered workflows — all within their
own infrastructure.

```
OpenKubes AI
├── Ollama          — LLM runtime with GPU acceleration
├── Open WebUI      — Private chat interface (like ChatGPT, but yours)
├── MCP Connectors  — Connect LLMs to Jira, Confluence, Git, ...
└── (planned) RAG   — Retrieval Augmented Generation over your docs
```

---

## Architecture

```
Infrastructure Layer (ok-gpu, RKE2)
└── Ollama + GPU  →  central LLM endpoint (internal only)

Workload Clusters (ok1-talos, ok2-talos, ...)
└── Open WebUI    →  connects to central Ollama
└── MCP Server    →  connects LLM to Jira, Confluence, ...
```

The central Ollama instance serves all workload clusters — one GPU, many teams.
See [ADR-Platform-005](../../architecture/decisions/ADR-Platform-005-shared-ai-services.md)
for the architecture decision.

---

## Components

| Component | Description | Status |
|---|---|---|
| [ollama/](ollama/) | LLM inference server with GPU | ✅ deployed |
| [open-webui/](open-webui/) | Private chat UI | ✅ deployed |
| mcp/ | MCP connectors (Jira, Confluence) | 📋 planned |
| rag/ | Retrieval Augmented Generation | 📋 planned |

---

## Models

| Model | Size | Use Case |
|---|---|---|
| `mistral` | 7.2B, 4.1GB | General purpose, fast responses |
| `llama3` | 8B, ~4.7GB | Strong reasoning (planned) |
| `codellama` | 7B, ~3.8GB | Code generation (planned) |

---

## Quick Start

```bash
# Deploy Ollama with GPU (on RKE2 host cluster)
# See: ollama/README.md

# Deploy Open WebUI (on any workload cluster)
helm repo add open-webui https://helm.openwebui.com/
helm install open-webui open-webui/open-webui \
  --namespace open-webui \
  --create-namespace \
  -f open-webui/values.yaml
```

Provider-specific overrides (GPU node IP, LoadBalancer pool) go into your
private infrastructure repo — see `open-webui/values.yaml` for the defaults.

---

## Related

- [ADR-Platform-005](../../architecture/decisions/ADR-Platform-005-shared-ai-services.md) — Shared AI Services architecture decision
- [Kubernauts OpenKubes AI](https://kubernauts.de/de/openkubes/openkubes-ai/) — product page
