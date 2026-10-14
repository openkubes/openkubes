# Open WebUI on OpenKubes

**A self-hosted AI chat interface, composed as a platform capability.**

OpenKubes provides an Open WebUI component and a Crossplane `OpenWebUIClaim` example. The chat frontend can use an internal model-serving backend such as Ollama. An existing workload cluster, storage provisioning, network connectivity and operator-approved provider values are prerequisites.

## Component boundaries

| Layer | Responsibility |
| --- | --- |
| Open WebUI | Multi-user AI chat frontend |
| Crossplane `OpenWebUIClaim` | Declarative desired state and target cluster selection |
| Model backend | Inference endpoint operated separately |
| Cluster infrastructure | Networking, storage and appropriate runtime policy |

**Not a one-line universal installer:** Claims and Helm examples need a provisioned target cluster and correct provider-specific settings. Do not copy example endpoints or storage/security policies directly into a production environment.

## Documentation and examples

- [Component README](https://github.com/openkubes/openkubes/blob/main/platform/ai/open-webui/README.md) — prerequisites, installation paths and operational caveats.
- [Crossplane claim examples](https://github.com/openkubes/openkubes/tree/main/platform/ai/open-webui/crossplane/examples) — illustrative manifests, not production-specific values.
- [Crossplane implementation](https://github.com/openkubes/openkubes/tree/main/platform/ai/open-webui/crossplane) — XRD and composition.
- [OK AI overview](index.md) — how the capability fits into the broader platform.

For the exact supported deployment procedure, follow the component's maintained README and the runbook for your chosen cluster.
