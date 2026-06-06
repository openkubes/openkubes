# Contributing to {{REPO_TITLE}}

Thanks for contributing to OpenKubes. This guide covers the **make-based workflow** used across all OpenKubes repositories.

---

## make-based Development Workflow

All developer actions go through `make`. Do not run `kubectl apply`, `helm install`, or `flux` commands directly — wrap them in targets or use the existing ones.

```sh
make help          # start here
make dev           # local dev setup (k3s / kind)
make lint          # validate before committing
make diff          # dry-run diff against cluster
make install       # deploy
make verify        # confirm state
make clean         # teardown
```

---

## Local Development Setup

### Requirements

- `make` ≥ 3.81
- `kubectl` configured
- `jq` (used in scripts — no Python dependency)
- `yamllint` for linting
- `helm` / `flux` / `clusterctl` as needed per component

### Bootstrap local environment

```sh
git clone https://github.com/openkubes/{{REPO_NAME}}.git
cd {{REPO_NAME}}
cp .env.example .env
make dev
```

---

## Makefile Conventions

All OpenKubes Makefiles follow these conventions:

### Standard targets (every repo must have these)

| Target | Purpose |
|---|---|
| `help` | Print all targets with descriptions (auto-generated from `##` comments) |
| `install` | Idempotent install / deploy |
| `verify` | Non-destructive status check |
| `upgrade` | In-place upgrade using version from `.env` |
| `clean` | Full teardown of managed resources |
| `lint` | Static analysis — yamllint + kyverno dry-run |
| `diff` | Dry-run diff without applying |

### `help` target pattern

Every Makefile must include this self-documenting `help` target:

```makefile
.DEFAULT_GOAL := help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

.PHONY: help install verify upgrade clean lint diff
```

### Document every target with `##`

```makefile
install: ## Install this component on the management cluster
	kubectl apply -f manifests/

verify: ## Check pods and CRD readiness
	kubectl get pods -n $(NAMESPACE)
```

### Use `.env` for all version pins and configuration

```makefile
include .env
export

install: ## Install component at version $(COMPONENT_VERSION)
	helm upgrade --install $(RELEASE_NAME) $(CHART) \
		--version $(COMPONENT_VERSION) \
		--namespace $(NAMESPACE) \
		--create-namespace
```

### No Python — use `jq` for JSON/YAML processing

```makefile
# WRONG
get-status:
	kubectl get ... -o json | python3 -c "import json,sys; ..."

# RIGHT
get-status: ## Get component status
	kubectl get ... -o json | jq '.status'
```

---

## Branching & Commits

```
main          stable, protected — PRs only
dev           active development
release/vX.Y  release preparation
fix/short-desc  bugfixes
feat/short-desc new features
```

Commit message format:

```
<type>(<scope>): <short summary>

fix(crossplane): replace python3 with jq in upgrade script
feat(capi): add make target for external-infra-kubeconfig
docs(readme): update quick start with make-first workflow
chore(makefile): add lint and diff targets
```

---

## Pull Request Checklist

- [ ] `make lint` passes without errors
- [ ] `make diff` reviewed — no unintended changes
- [ ] New targets documented with `##` comment
- [ ] `.env.example` updated if new variables added
- [ ] `CHANGELOG.md` entry added
- [ ] README updated if user-facing behaviour changed

---

## Releasing

Releases are cut from `main` using the standard make target:

```sh
# Maintainers only
VERSION=v1.0.3 make release
```

This tags the commit, updates `CHANGELOG.md`, and triggers the GitHub Actions release workflow.

---

## Questions?

Open a [GitHub Discussion](https://github.com/openkubes/openkubes/discussions) or join the [Kubernauts Meetup](https://www.meetup.com/kubernauts/).
