# Contributing to OpenKubes

Thanks for contributing to OpenKubes. This guide covers the **make-based workflow** used across all OpenKubes repositories.

---

## make-based Development Workflow

All developer actions go through `make`. Do not run `kubectl apply`, `helm install`, or `flux` commands directly — wrap them in targets or use the existing ones.

```sh
make help          # start here — lists all targets
make dev           # local dev setup (k3s / kind)
make lint          # validate manifests before committing
make diff          # dry-run diff against cluster
make install       # deploy
make verify        # confirm platform state
make clean         # full teardown
make debug         # collect diagnostics
```

---

## Local Development Setup

### Requirements

| Tool | Version | Notes |
|---|---|---|
| make | ≥ 3.81 | GNU make |
| kubectl | latest | configured with cluster access |
| jq | ≥ 1.6 | JSON/YAML processing — no Python |
| yamllint | latest | manifest linting |
| helm | ≥ 3.14 | Crossplane + addons |
| flux | ≥ 2.x | GitOps bootstrap |
| clusterctl | latest | CAPI bootstrap |

### Bootstrap local environment

```sh
git clone https://github.com/openkubes/openkubes.git
cd openkubes
cp .env.example .env    # adjust versions as needed
make dev
```

---

## Makefile Conventions

All OpenKubes Makefiles follow these conventions:

### Standard targets (every component must have these)

| Target | Purpose |
|---|---|
| `help` | Print all targets with descriptions (auto-generated) |
| `install` | Idempotent install / deploy |
| `verify` | Non-destructive status check |
| `upgrade` | In-place upgrade using version from `.env` |
| `clean` | Full teardown of managed resources |
| `lint` | Static analysis — yamllint |
| `diff` | Dry-run diff without applying |
| `debug` | Collect diagnostic snapshot |

### Self-documenting `help` target (required in every Makefile)

```makefile
.DEFAULT_GOAL := help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-25s\033[0m %s\n", $$1, $$2}'

.PHONY: help install verify upgrade clean lint diff debug
```

### Document every target with `##`

```makefile
crossplane-install: ## Install Crossplane $(CROSSPLANE_VERSION)
	helm upgrade --install crossplane crossplane-stable/crossplane \
		--namespace $(CROSSPLANE_NAMESPACE) \
		--version $(CROSSPLANE_VERSION) \
		--create-namespace

crossplane-upgrade: ## Upgrade Crossplane to version in .env
	$(MAKE) crossplane-install
```

### Use `.env` for all version pins

```makefile
include .env
export

# .env.example:
# CROSSPLANE_VERSION=v2.2.0
# KUBEVIRT_VERSION=v1.8.1
# CAPK_VERSION=v0.11.2
```

Override at runtime:

```sh
CROSSPLANE_VERSION=v2.3.0 make crossplane-upgrade
```

### No Python — use `jq` for all JSON/YAML processing

```makefile
# WRONG — python3 dependency, fragile
get-status:
	kubectl get xrd -o json | python3 -c "import json,sys; ..."

# RIGHT — jq, consistent across all environments
get-status: ## Get Crossplane XRD status
	kubectl get xrd -o json | jq '.items[].status.conditions'
```

---

## Branching & Commits

```
main              stable, protected — PRs only
dev               active development
release/vX.Y.Z    release preparation
fix/short-desc    bugfixes
feat/short-desc   new features
docs/short-desc   documentation only
```

Commit message format:

```
<type>(<scope>): <short summary>
```

Examples:

```
fix(crossplane): replace python3 with jq in crossplane-upgrade.sh
feat(capi): add make target for external-infra-kubeconfig
docs(readme): update quick start with make-first workflow
chore(makefile): add lint and diff targets to all components
release(v1.0.3): crossplane jq fix + make targets
```

---

## Pull Request Checklist

- [ ] `make lint` passes without errors
- [ ] `make diff` reviewed — no unintended cluster changes
- [ ] New `make` targets documented with `##` comment
- [ ] `.env.example` updated if new variables added
- [ ] `CHANGELOG.md` entry added under `[Unreleased]`
- [ ] README updated if user-facing behaviour changed
- [ ] No raw `kubectl` / `helm` / `flux` commands in scripts — use make targets

---

## Releasing

Releases are cut from `main` by maintainers:

```sh
# Bump version in .env and CHANGELOG.md, then:
VERSION=v1.0.3 make release
```

This tags the commit and triggers the GitHub Actions release workflow.

Current release: **v1.0.2** · Next planned: **v1.0.3** (crossplane-upgrade.sh jq fix)

---

## Open Issues & Planned Work

| Issue | Target | Notes |
|---|---|---|
| `crossplane-upgrade.sh`: `python3` → `jq` | v1.0.3 | See `platform/cluster-management/` |
| GitOps with Flux | backlog | Coordination with team needed |
| OpenKubes-Docu | backlog | MkDocs Material @ docs.openkubes.ai |

---

## Questions?

Open a [GitHub Issue](https://github.com/openkubes/openkubes/issues) or join the [Kubernauts Meetup](https://www.meetup.com/kubernauts/).
