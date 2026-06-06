# {{REPO_TITLE}}

<!-- SHIELDS -->
![Release](https://img.shields.io/github/v/release/openkubes/{{REPO_NAME}})
![License](https://img.shields.io/github/license/openkubes/{{REPO_NAME}})
![Status](https://img.shields.io/badge/status-{{STATUS_BADGE}}-{{STATUS_COLOR}})

> **{{REPO_TAGLINE}}**

Part of the [OpenKubes](https://github.com/openkubes/openkubes) runtime distribution.

| Repository | Purpose |
|---|---|
| [`openkubes/openkubes`](https://github.com/openkubes/openkubes) | Core Runtime Distribution |
| [`openkubes/openkubes-robotics`](https://github.com/openkubes/openkubes-robotics) | Fleet Orchestration & Industrial Automation |
| [`openkubes/openkubes-ai`](https://github.com/openkubes/openkubes-ai) | AI Inference & Model Runtime |
| [`openkubes/openkubes-quantum`](https://github.com/openkubes/openkubes-quantum) | Hybrid Quantum-Classical Runtime |

---

## Quick Start

```sh
make help          # all available targets
make install       # install this component
make verify        # check status
make upgrade       # upgrade to latest version
make clean         # uninstall / teardown
```

> All targets are idempotent. Run `make help` first to see what's available for this component.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Kubernetes | ≥ 1.29 | RKE2 recommended for production |
| kubectl | latest | configured with cluster access |
| make | ≥ 3.81 | GNU make |
| {{EXTRA_DEP_1}} | {{EXTRA_DEP_1_VERSION}} | {{EXTRA_DEP_1_NOTE}} |

---

## Installation

### 1. Clone & configure

```sh
git clone https://github.com/openkubes/{{REPO_NAME}}.git
cd {{REPO_NAME}}
cp .env.example .env        # adjust values as needed
```

### 2. Install

```sh
make install
```

<details>
<summary>What <code>make install</code> does</summary>

```
{{INSTALL_STEPS_DETAIL}}
```

</details>

### 3. Verify

```sh
make verify
```

Expected output:

```
{{VERIFY_EXPECTED_OUTPUT}}
```

---

## make Targets

```sh
make help
```

| Target | Description |
|---|---|
| `make install` | Install / deploy this component |
| `make verify` | Check pods, CRDs and readiness |
| `make upgrade` | Upgrade to the version defined in `.env` |
| `make clean` | Remove all resources created by `make install` |
| `make dev` | Deploy in dev / local mode (k3s / kind) |
| `make lint` | Lint manifests (yamllint + kyverno dry-run) |
| `make diff` | Dry-run diff against current cluster state |
| `{{EXTRA_TARGET}}` | {{EXTRA_TARGET_DESC}} |

> Targets marked with `*` require cluster admin privileges.

---

## Configuration

All configuration is managed via `.env` (copy from `.env.example`):

```sh
# Component version
{{COMPONENT_NAME}}_VERSION=v{{DEFAULT_VERSION}}

# Namespace
{{COMPONENT_NAME}}_NAMESPACE={{DEFAULT_NAMESPACE}}

# Optional overrides
# {{COMPONENT_NAME}}_VALUES_FILE=./values.custom.yaml
```

Environment variables override `.env` values at runtime:

```sh
{{COMPONENT_NAME}}_VERSION=v1.2.3 make install
```

---

## Architecture

```
{{ASCII_ARCHITECTURE_DIAGRAM}}
```

→ Full architecture deep dive: [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md)

---

## GitOps Integration

This component ships with a Flux `HelmRelease` / `Kustomization` manifest:

```sh
# Bootstrap via Flux (managed by your GitOps repo)
make gitops-bootstrap

# Or apply manually
kubectl apply -f gitops/
```

→ See [`platform/gitops/fluxcd/`](https://github.com/openkubes/openkubes/tree/main/platform/gitops/fluxcd) in the core repo.

---

## Upgrading

```sh
# Edit version in .env, then:
make upgrade

# Verify after upgrade
make verify
```

For breaking changes, see [`CHANGELOG.md`](./CHANGELOG.md).

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| Pods in `CrashLoopBackOff` | Missing secret or config | Check `make verify` output |
| `make install` fails at step 2 | Version mismatch | Update `_VERSION` in `.env` |
| CRDs not registered | Previous install incomplete | Run `make clean && make install` |

```sh
# Collect debug info
make debug
```

---

## Contributing

See [`CONTRIBUTING.md`](./CONTRIBUTING.md). In short:

```sh
make lint          # before committing
make diff          # review cluster impact
```

Branches: `main` (stable) · `dev` (active development) · `release/vX.Y.Z` (release prep)

---

## Community & Support

| | |
|---|---|
| 🌍 Worldwide Meetup | [meetup.com/kubernauts](https://www.meetup.com/kubernauts/) |
| 📺 YouTube | [youtube.com/c/kubernautsio](https://www.youtube.com/c/kubernautsio) |
| 🤖 Live Demo | [rmf.openkubes.ai](https://rmf.openkubes.ai/dashboard/login) |
| 🌐 Docs | [docs.openkubes.ai](https://docs.openkubes.ai) *(coming soon)* |
| 💬 Enterprise | [kubernauts.de](https://kubernauts.de) |

---

## License

[Apache 2.0](./LICENSE) · Built by [Kubernauts GmbH](https://kubernauts.de) · Cologne, Germany
