# ADR-Platform-005: Shared AI Services Layer — Centralized GPU Backend for all Workload Clusters

**Date:** 2026-07-01  
**Status:** Accepted  
**Amended:** 2026-07-19; 2026-07-21 — core centralized-inference and self-service decisions unchanged; documented Open WebUI default topology amended (see Amendment notes below)  

---

## Context

OpenKubes runs multiple Kubernetes workload clusters (ok1-talos, ok2-talos, ...) on top of an RKE2 host cluster with a dedicated GPU node (ok-gpu: Hetzner GEX44, NVIDIA RTX 4000 SFF Ada Generation, 20GB VRAM).

The team needs a Private GPT stack — LLM inference + a developer-facing chat UI — for internal use. The question is: where should AI services (LLM backend, model storage, GPU utilization) live in the OpenKubes platform architecture?

Several deployment models were considered:

1. **Per-cluster:** Every workload cluster runs its own Ollama + GPU
2. **GPU Passthrough:** KubeVirt VMs get direct GPU access via VFIO/IOMMU
3. **Shared central backend:** One Ollama instance on the host cluster, all workload clusters connect to it

---

## Decision

> AI services follow the same contract model as the rest of the OpenKubes platform: one central backend owned by the infrastructure layer, consumed by workload clusters via a stable internal endpoint.

Concretely:

```
ok-infra (RKE2 Host-Cluster)
└── ok-gpu node (RTX 4000 Ada, nvidia.com/gpu: 1)
    └── Ollama  →  MetalLB LoadBalancer (internal, e.g. 192.168.100.21x)

ok1-talos ──────────────────┐
ok2-talos ──────────────────┼──→ http://<ollama-ip>:11434  (Ollama API)
ok3-talos ──────────────────┘
    └── Open WebUI (per cluster/team)
```

**GPU stays on the host cluster.** Workload clusters consume AI services via a stable internal IP — they do not own GPU resources.

---

## Rationale

**1. GPU Passthrough is not viable today.**
IOMMU/VT-d was found to be disabled on ok-gpu's UEFI (confirmed 2026-07-01: `dmesg | grep -i iommu` returns empty). Enabling it requires a Hetzner support ticket and a server reboot — risky for a production node that also runs all workload cluster VMs. GPU Passthrough remains a future option, not a current path.

**2. Per-cluster AI is wasteful and operationally complex.**
20GB VRAM split across multiple clusters means no cluster gets meaningful GPU resources. Each cluster would need its own model downloads (large, slow), its own GPU scheduling, and its own update cadence. With one central Ollama, models are downloaded once and served to all.

**3. Shared backend follows ADR-Platform-001.**
"OpenKubes owns the contracts, not the components." The AI contract is: *give me LLM inference at this endpoint*. Which model, which GPU, which runtime — that is the infrastructure layer's responsibility, not the workload cluster's. This mirrors how ok-linux owns the OS contract and ok-cluster just says `profile: kubevirt`.

**4. MetalLB internal endpoint is the stable contract.**
The Ollama LoadBalancer IP is the seam between the AI infrastructure layer and the workload clusters — analogous to `os.schematic_id` in ok-cluster. Today it is set manually; in the future it could be resolved via a Crossplane Composition or a platform config API.

**5. Self-service comes later.**
A `OllamaModelClaim` Crossplane XRD would allow teams to request models without admin intervention. This is the correct long-term direction but is deferred until the basic stack is validated in production — following the same "understand before you change" principle applied throughout the platform.

---

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| GPU Passthrough via VFIO/IOMMU | IOMMU disabled on ok-gpu UEFI; enabling requires Hetzner support + reboot; risk to production VMs |
| Per-cluster Ollama (no GPU) | CPU-only inference is too slow for developer productivity; defeats the purpose of having a GPU |
| Per-cluster Ollama (with GPU) | Only one GPU available; cannot be shared across multiple clusters natively |
| Public cloud GPU (e.g. AWS, GCP) | Contradicts the "sovereign, local-first" positioning of OpenKubes; cost unpredictable |

---

## Consequences

**Positive:**
- One GPU serves all workload clusters — maximum utilization, no waste
- Models downloaded once, served to all teams
- Workload clusters stay stateless with respect to AI — they just point to an endpoint
- Consistent with ADR-Platform-001/002: infrastructure layer owns the GPU contract

**Negative / trade-offs:**
- Ollama on the host cluster is a single point of failure for AI services — no redundancy
- Workload clusters depend on an internal IP — if Ollama is down, all Open WebUI instances lose backend
- GPU is shared: high inference load on one cluster affects all others (no isolation today)

**Neutral:**
- Open WebUI per cluster/team is a deliberate choice — each team gets their own chat history, user management, and model selection UI, while sharing the GPU backend

---

## Implementation plan

| Step | Story | Description |
|---|---|---|
| 1 | [OK-52](https://kubernauts.atlassian.net/browse/OK-52) | Deploy Ollama with GPU on RKE2 host cluster, expose via MetalLB |
| 2 | [OK-53](https://kubernauts.atlassian.net/browse/OK-53) | Deploy Open WebUI on ok1-talos, connect to central Ollama endpoint |
| 3 | [OK-54](https://kubernauts.atlassian.net/browse/OK-54) | Define model management strategy, plan future OllamaModelClaim |

**Repository for manifests:** `gitlab.com/kubernauts/hetzner` → `ok-rke2/ai-services/` *(private; see Amendment note)*

---

## Re-evaluation triggers

Revisit this ADR if:
- IOMMU/VT-d becomes available on ok-gpu (GPU Passthrough path opens up)
- A second GPU node is added — redundancy and isolation become viable
- A team requires GPU isolation (e.g. compliance, model confidentiality)
- Self-service model management (OllamaModelClaim) is implemented — may change the ownership model
- Ollama is adopted as a shared platform service in `ok-shared` (ADR-Platform-020 service table) — ownership would move from ok-infra to ok-shared *(added 2026-07-19)*

---

## Amendment note (2026-07-19)

The decision stands; the architecture runs as decided (central Ollama on ok-infra, Open WebUI per workload cluster — the latter now provisioned self-service via the `OpenWebUIClaim` XRD, fulfilling the deferred direction in Rationale 5). This amendment records three factual updates, no new decisions:

1. **New re-evaluation trigger (ADR-Platform-020):** the ADR-020 service table lists Ollama as a candidate shared platform service. Its adoption into `ok-shared` would move ownership from the ok-infra host cluster and must trigger a revisit — added to the trigger list above.
2. **Re-reading under ADR-Platform-022:** Rationale 3 calls "give me LLM inference at this endpoint" the AI contract. Under the framework reading, the endpoint IP is **Provider Values**, not a contract artifact; a formal LLM Inference Capability Contract does not (yet) exist and is deliberately absent from the contracts inventory. Formalization awaits a forcing consumer ("no structure without a forcing consumer").
3. **Manifest repository status confirmed:** the Ollama manifests remain in the private `hetzner` repository (`ok-rke2/ai-services/ollama`). This is consistent with ADR-022's Provider-Values reading (site-specific manifests are never framework artifacts) and stays as-is until a public-capable `ok-rke2` repository exists.

## Amendment note (2026-07-21)

[ADR-Platform-015's Addendum](ADR-Platform-015-agentic-ai.md#addendum-2026-07-21-multi-cluster-deployment-scope) amends the default Open WebUI deployment topology documented above ("Open WebUI per cluster/team") without changing this ADR's core decisions on centralized inference and self-service provisioning. A dedicated instance per workload cluster is no longer the *only* supported topology: a shared Open WebUI instance (currently ok-ai) may serve Agent Backends registered from other clusters (ok-shared, ok-robotics — intended, tracked via OK-87/OK-92, not yet deployed) that don't otherwise need a per-team chat UI, while the dedicated-instance path via `OpenWebUIClaim` remains available unchanged for any team/cluster that does.
