# OK AI — AI Workloads & Agentic Operations

**Your Kubernetes Framework. Built for the Age of AI.**

OK AI is the AI capability area of OpenKubes: run self-hosted AI services on Kubernetes and explore explicitly constrained, evidence-driven agent integrations. It is a **platform capability**, not a separate Kubernetes distribution or a separate `ok-ai` source repository.

## OK AI Chat — first UI preview

[**Explore the OK AI Chat UI prototype →**](chat-preview.md) — an interactive visual preview with sample responses only. It does **not** send any questions to an AI service or public API. No login required.

## OK AI roadmap

Explore our [three-phase OK AI roadmap](ai-roadmap.md): **Documentation Assistant → Read-only Diagnostics → Agentic Operations**. The Documentation Assistant has passed an isolated private lab format-and-source-ID integration check; the public service is not yet released.

## Explore OK AI

| Capability | Purpose | Documentation |
| --- | --- | --- |
| **Open WebUI** | Self-hosted chat frontend for AI backends | [Open WebUI](open-webui.md) |
| **OpenClaw** | Optional agent backend through the Agent Interface Contract | [OpenClaw](openclaw.md) |
| **kagent & Platform Diagnostics** | Read-only diagnostics provider behind the HTTP/OpenAPI contract | [kagent & Platform Diagnostics](kagent-platform-diagnostics.md) |
| **Agentic Operations** | Proposal, policy, authorization, execution and evidence boundaries | [Agentic Operations](agentic-operations.md) |
| **AI Glossary** | Beginner-friendly explanations of AI concepts, from LLMs to agents, RAG and evals | [AI Glossary](ai-glossary-newbies.md) |

## Architecture at a glance

OpenKubes separates the management plane, AI workloads, model-serving endpoints and optional agents. The framework defines contracts; selected ecosystem components implement them.

- **Management plane:** Crossplane claims can reconcile AI services onto authorized workload clusters.
- **AI workload cluster (`ok-ai`):** Hosts AI-facing services such as Open WebUI where provisioned.
- **Model backend:** GPU-backed services such as Ollama can be provided separately, subject to infrastructure and network configuration.
- **Agent boundary:** Optional agents consume explicitly defined interfaces and must not silently inherit unrestricted Kubernetes access.

The repository's [AI platform overview](https://github.com/openkubes/openkubes/blob/main/platform/ai/README.md) documents the architecture and historical deployment examples. Treat examples as environment-specific until prerequisites and versions have been verified.

## Start here

1. New to OpenKubes? Use [Getting Started](../getting-started/) to choose Local or Cluster first.
2. Have a Kubernetes workload cluster? Read [Open WebUI](open-webui.md) and its upstream component README.
3. Evaluating agents? Read [OpenClaw](openclaw.md), [kagent & Platform Diagnostics](kagent-platform-diagnostics.md), [Agentic Operations](agentic-operations.md), and the relevant ADRs before live tests.

**Source ownership:** AI components are maintained in [`openkubes/openkubes/platform/ai/`](https://github.com/openkubes/openkubes/tree/main/platform/ai); cluster-specific deployment inputs belong to the respective operator environment and repository. This website is a guided entry point, not a replacement for the source-owned runbooks.
