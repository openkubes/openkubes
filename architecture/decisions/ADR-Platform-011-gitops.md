# ADR-Platform-011: GitOps for OpenKubes Cluster Lifecycle

**Status:** Proposed
**Date:** 2026-07-07
**Related:** OK-58, ADR-Platform-001 (contracts not components), ADR-Platform-010 (ingress)

## Context

OpenKubes currently uses an imperative workflow for cluster lifecycle:

```
Developer → make new → make bootstrap → CAPI creates cluster
```

State lives in two places: local rendered manifests (git-ignored) and CAPI objects on the
host cluster (ok-infra). This creates two known problems:

1. **Teardown without local manifests fails** — if a cluster was bootstrapped by another
   developer (e.g. Daniel) or on another machine, `make teardown` cannot find the local
   directory and fails silently. Fixed short-term by making `teardown` work directly via
   CAPI (ADR-Platform-010 era, option 2), and by committing rendered manifests (`.gitignore`
   loosened 2026-07-07).
2. **No declarative cluster state** — desired state is not expressed in Git. Drift between
   Git and live clusters is not detected. Rollback requires manual intervention.

The OpenKubes platform principle "contracts not components" implies that the *cluster
lifecycle contract* (what clusters exist, with what configuration) should be expressible
as a Git-committed artifact — not as a sequence of `make` commands.

## Decision (proposed)

Introduce `ok-gitops` as the fourth platform capability, implementing GitOps for cluster
lifecycle via ArgoCD.

### Contract (stable)

1. Git is the single source of truth for cluster desired state.
2. Rendered cluster manifests live in a dedicated `rendered/` directory (or separate repo)
   — not mixed with templates.
3. Creating a cluster = committing a rendered manifest + pushing.
4. Deleting a cluster = removing the manifest from Git + pushing.
5. ArgoCD reconciles Git state → CAPI objects on the host cluster.

### Implementation Profile v1: ArgoCD + App-of-Apps

- ArgoCD installed on ok-mgmt (existing management cluster).
- App-of-Apps pattern: one root `Application` per cluster namespace, child `Application`
  objects for each capability (cni, storage, ingress).
- `make new` renders manifests and commits to `rendered/<cluster>/` — no direct `kubectl
  apply` in the deploy path.
- `make teardown` becomes `git rm rendered/<cluster>/ && git push`.
- Bootstrap stack (Crossplane, providers, XRDs) expressed as ArgoCD `Application` objects
  — replaces `bootstrap-mgmt.sh` imperative script.

### Secrets strategy

Cluster kubeconfigs and CAPK infra credentials cannot be committed. Options (to be decided
in implementation):
- External Secrets Operator (ESO) + Hetzner Vault / Bitwarden
- Sealed Secrets (simpler, no external dependency)
- SOPS + age encryption (Git-native, no operator required)

### Migration path from current state

1. Install ArgoCD on ok-mgmt (`make install-gitops` — new opt-in capability target).
2. Commit existing rendered manifests to `rendered/` (`.gitignore` already loosened).
3. Create ArgoCD `Application` pointing at `rendered/`.
4. Retire imperative `bootstrap` + `install` targets progressively.

## Alternatives Considered

- **Flux** — functionally equivalent to ArgoCD for this use case; ArgoCD preferred for
  its UI and existing team familiarity.
- **Keep imperative workflow** — viable short-term (`.gitignore` loosened, `teardown` via
  CAPI). Does not address drift detection or multi-developer coordination.

## Consequences

- `ok-cluster` Makefile targets become thin wrappers around `git commit/push` rather than
  direct `kubectl apply`.
- `.gitignore` stays open for rendered manifests until `rendered/` separation is
  implemented.
- `bootstrap-mgmt.sh` is deprecated in favour of ArgoCD `Application` manifests —
  no ADR amendment needed, it is an implementation detail.
- Secrets management requires a decision before implementation (see above).
- `make e2e` remains valid for local development and CI — GitOps is the production path.
