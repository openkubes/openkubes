# ADR-Platform-011: GitOps for OpenKubes Cluster Lifecycle

**Status:** Proposed
**Date:** 2026-07-07
**Related:** OK-58, OK-71 (Secret Contract amendment), OK-67, OK-109, OK-110, ADR-Platform-001 (contracts not components), ADR-Platform-009 (Storage), ADR-Platform-010 (ingress), ADR-Platform-016 (OS), ADR-Platform-017 (Constraint Envelopes)

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

1. Git is the source of truth for declarative cluster lifecycle state and for references to externally managed secret material; plaintext secret values are never required to reside in Git (see the Secret Contract below).
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

### Secret Contract (amendment 2026-07-25 — OK-71; three-way review 2026-07-10)

> **Amendment status: Accepted / normative** — normative as of the human merge
> of this amendment (OK-71; three-way review 2026-07-10 & 2026-07-25). The merge
> is the acceptance act, not the review alone.
> **GitOps Implementation Profile status: Proposed** — ArgoCD, `rendered/`, and
> the migration path remain open. This ADR deliberately carries an Accepted
> amendment inside an otherwise-Proposed decision; the document `Status:` header
> tracks the profile.

Cluster kubeconfigs, CAPK infra credentials, and application admin credentials
cannot be committed. Their handling is governed by a technology-independent
contract:

1. **Git never contains plaintext secret material.**
2. **Git is the source of truth for the declarative references and reconciliation
   configuration of secret material — but not necessarily for the secret values
   themselves** (which may live in an external store, e.g. Vault/Bitwarden).
3. **Secret material MUST be reconcilable within the constraint envelope of the
   cluster or environment in which its reconciliation occurs.** Mechanisms that
   require an always-on external service are valid only where that envelope
   guarantees the required connectivity and service availability. So a workload
   credential is judged against the workload cluster's envelope; a CAPK / CAPI /
   kubeconfig credential against the management / host cluster's envelope that
   actually reconciles it — not against the (possibly edge) target it refers to.

Consequences:

- The secret **tool** (External Secrets Operator, SOPS, Sealed Secrets, Vault,
  Bitwarden, …) is an **Implementation Profile per envelope — not part of the
  contract**.
- **Datacenter envelope:** ESO / SOPS / Sealed all valid (e.g. Vault + ESO on
  ok-shared — OK-110). **Constrained-edge envelope:** offline-reconcilable
  mechanisms only (SOPS / Sealed-class).
- Third precedent for the Constraint Envelope pattern (ADR-017), after storage
  (ADR-009) and OS (ADR-016).
- Adds an evaluation criterion to the edge GitOps spike (OK-67).

This supersedes the earlier "options to be decided in implementation" wording.

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
- Secrets management follows the **Secret Contract** above; the concrete tool is a per-envelope Implementation Profile (datacenter: e.g. Vault + ESO — OK-110; constrained-edge: SOPS / Sealed-class). The contract is settled even though the GitOps profile is still Proposed.
- `make e2e` remains valid for local development and CI — GitOps is the production path.
