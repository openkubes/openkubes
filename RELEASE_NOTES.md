# OpenKubes Release Notes

---

## v0.14.0 — Central Identity and Governed Application Claims

> **Human intent is authenticated centrally and constrained before it becomes platform state.**

### What's New

**Central identity**
- The central Keycloak capability now provisions one platform realm, platform
  groups, and audience-bound clients for consuming clusters.
- The RMF Web application realm is provisioned separately while reusing the
  central Keycloak service instead of deploying an application-local identity
  provider.
- The cluster lifecycle repository consumes the Keycloak capability from an
  exact, pinned `openkubes` revision.

**Governed OpenRMF claims**
- OpenRMF claim editing is delegated to the platform OIDC group through
  least-privilege, namespace-scoped RBAC.
- Admission policy constrains identities to reviewed cluster, target,
  namespace, and hostname allocations before a Claim is accepted.
- Negative controls cover authorization widening, schema regressions,
  credential redirection, and unsafe delegation during XRD updates.

**Cluster and OS contracts**
- Talos KubeVirt scheduling is now selected through reviewed provider profiles,
  including production `ok-gpu` and isolated single-replica development storage.
- Free-form scheduling and consumer-side storage overrides fail closed; the
  existing Talos Golden Image identity remains pinned.
- ADR-Platform-029 is accepted as the OpenKubes messaging capability contract.

### Release Train

| Repository | Release |
|---|---:|
| `openkubes/openkubes` | `v0.14.0` |
| `openkubes/ok-cluster` | `v0.14.0` |
| `openkubes/ok-linux` | `v0.3.0` |
| `openkubes/ok-observability` | `v0.13.0` |
| `openkubes/ok-storage` | `v0.1.1` |
| `openkubes/ok-local` | `v0.1.0` |

---

## v0.13.0 — Launch Meetup Community Preview

> **A framework for building sovereign Kubernetes platform distributions.**

### What's New

**Sovereign platform services**
- Vault + Vault Secrets Operator is now the datacenter Secret Contract profile,
  including consumer onboarding, scoped self-service seeding, backup/restore,
  outage recovery, Transit auto-unseal, and singleton enforcement evidence.
- The central Keycloak capability adds TLS, hardening, backup/restore, credential
  rotation, and conformance tooling. Cluster-side installation remains an
  explicit follow-up and is not claimed as part of this release.

**Immutable OS and cluster lifecycle**
- Constrained Flatcar support is validated and promoted for KubeVirt, including
  replacement-based lifecycle and Longhorn-backed 50 GiB boot clones.
- Talos v1.9.6 Golden Images are pinned, verified, and consumed through local
  CSI snapshot clones, with guarded replacement and cleanup evidence.
- A controlled Flatcar/Talos provisioning benchmark records comparable lifecycle
  milestones without broadening the supported platform contract.

**Diagnostics, verticals, and governance**
- The read-only platform diagnostics contract and kagent Profile A establish a
  grounded, evidence-first diagnostics boundary.
- The vertical-layer decision accepts `ok-robotics`, `ok-ai`, and `ok-iot` as
  forcing consumers; messaging and artifact-registry capability contracts are
  published as drafts for review.
- Canonical naming, additional acceptance records, and the Launch Meetup deck
  bring the public documentation in line with the implemented platform.

### Release Train

| Repository | Release |
|---|---:|
| `openkubes/openkubes` | `v0.13.0` |
| `openkubes/ok-cluster` | `v0.13.0` |
| `openkubes/ok-observability` | `v0.13.0` |
| `openkubes/ok-linux` | `v0.2.0` |
| `openkubes/ok-storage` | `v0.1.1` |
| `openkubes/ok-local` | `v0.1.0` |

---

## v0.12.0 — Observability Capability + Harness Engineering

> **OpenKubes owns the contracts, not the components.**

### What's New

**Observability Capability (ADR-Platform-018)**
- Gated `make install-observability` in ok-cluster (OK-79): deploys the `ok-observability-standard` profile (kube-prometheus-stack + OpenSearch + log collector) and runs the contract test. A cluster is observability-ready only when all five contract guarantees pass — metric ingestion, Grafana datasource, OpenSearch log search, alert delivery, and declarative registration.
- Secret-based, Vault-ready credentials model (`ok-observability-credentials`) — no plaintext passwords passed to Helm. Proven end-to-end on two independent clusters (ok-shared, ok-robotics).
- `openkubes/ok-observability` owns the capability (contract, charts, dashboards, alerting, contract test); ok-cluster installs and integrates it.

**Harness Engineering pilot — adopted (OK-100)**
- `AGENTS.md` repository guide + deterministic `make verify` / `conformance` / `evidence` entry points in ok-observability. Rule zero: *AI may analyze, propose, implement, and argue; only humans approve architecture decisions and merge changes.*
- The deterministic sensors caught real defects and let an agent self-correct from their output alone; the ownership boundary held (agent escalated architecture/merge decisions to a human). Documented in the blog post *The Contract Is the Guardrail*.

**New Platform ADRs**
- ADR-Platform-021: Read-Only Platform Diagnostics Contract *(draft)*
- ADR-Platform-022: OpenKubes is a distribution framework, not a distribution *(draft)*
- ADR-Platform-023: CAPI infrastructure providers as Implementation Profiles *(accepted)*

**Three repositories — three releases**
- openkubes/openkubes v0.12.0
- ok-cluster v0.12.0
- ok-observability v0.12.0

---

## v0.2.0 — Private AI Platform + Management Cluster Architecture

> **OpenKubes owns the contracts, not the components.**

### Zero to Private AI in minutes

```bash
make new CLUSTER=ok-mgmt TYPE=talos NODE_SELECTOR=ok-infra WORKERS=2
make bootstrap CLUSTER=ok-mgmt
bash bootstrap-mgmt.sh          # Crossplane + CAPI + 4 XRDs in ~2 min

make new CLUSTER=ok1-talos TYPE=talos WORKERS=1
make bootstrap CLUSTER=ok1-talos
make install-storage CLUSTER=ok1-talos

make deploy CLUSTER=ok1-talos   # Open WebUI deployed in ~90 seconds
# → http://localhost:8080 — mistral:latest, 7.2B, RTX 4000 Ada
```

### What's New

**OpenKubes AI Platform**
- Central Ollama with GPU (RTX 4000 Ada, 20GB VRAM) on RKE2 host cluster
- `OpenWebUIClaim` XRD + Composition — deploy Open WebUI on any cluster via `make deploy`
- mistral:latest, 7.2B, running fully on your own infrastructure
- MCP Connectors for Jira + Confluence planned as next step

**ok-mgmt — Management Cluster**
- Dedicated Talos-based management cluster on ok-infra (separate from workload clusters)
- `bootstrap-mgmt.sh.tpl` — 8-step automated bootstrap: Crossplane, Providers, Functions, CAPI+CAPK+Talos, infra secret, XRDs, RBAC, OpenWebUI XRD
- `make install-storage CLUSTER=<name>` — local-path-provisioner for Talos clusters
- Workload clusters deployed from ok-mgmt via Crossplane Claims — not from your laptop

**8 Platform ADRs**
- ADR-Platform-001: OpenKubes owns the contracts, not the components
- ADR-Platform-002: openkubes/openkubes is the Distribution and Integration Layer
- ADR-Platform-003: capi-platform-v4.2 as Platform Orchestrator prototype
- ADR-Platform-004: Runner is implementation detail — ok-cluster as shared backend
- ADR-Platform-005: Shared AI Services Layer
- ADR-Platform-006: ok-mgmt as Management Cluster
- ADR-Platform-007: CAPI responsibility split (ok-infra bootstraps, ok-mgmt operates)
- ADR-Platform-008: TYPE=talos-mgmt as dedicated cluster type

**Three repositories — three releases**
- openkubes/openkubes v0.2.0
- ok-cluster v0.7.0
- ok-linux v0.1.1
