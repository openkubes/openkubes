# ADR-Platform-013: Workload Cluster Registration Contract

## Status

Accepted — three-way review completed (Arash / Claude / GPT, 2026-07-09)

## Context

The management plane (ok-mgmt) deploys capabilities into workload clusters via
Crossplane provider-helm. For this to work, ok-mgmt needs credentials for each
target cluster. Until now this was a manual, cluster-specific procedure
(deployment guide, step 5), performed once for ok1-talos.

With ok2-rmf (second workload cluster, operated by a different cluster owner)
the registration path becomes a repeatable operation performed by multiple
people. Two problems have already materialized:

1. **Stale-secret trap:** after a workload cluster re-bootstrap (`make
   new+bootstrap`), the kubeconfig secret in ok-mgmt still holds the old
   cluster's CA and credentials. Compositions then fail with opaque TLS or
   auth errors, and the root cause is non-obvious.
2. **No contract:** secret names, namespaces, and ProviderConfig names were
   convention-by-example, not convention-by-decision. A second cluster forces
   the question.

Consistent with ADR-Platform-001, OpenKubes owns the *contract* for cluster
registration; the Make target is merely its reference implementation.

## Decision

> **Platform invariant: One cluster. One name. One credential source.**
>
> Every workload cluster has exactly one platform identity, represented by
> its cluster name. Everything else — secret, ProviderConfigs, future
> mechanisms — derives from that name.

### 1. Naming convention

For a workload cluster named `<cluster>`:

- Kubeconfig secret: `<cluster>-kubeconfig` in namespace `crossplane-system`
  on ok-mgmt, key `kubeconfig`.
- `ProviderConfig` (provider-helm): name `<cluster>`, referencing that secret.
- If additional providers are adopted later (e.g. provider-kubernetes), their
  `ProviderConfig` uses the same name `<cluster>` and the same secret. One
  cluster, one name, one credential source.

The cluster name is the single join key: XR/Claim specs reference the target
cluster exclusively via `providerConfigRef.name: <cluster>`.

### 2. Idempotency

Registration is **replace, not create**. Re-running the registration for an
existing cluster overwrites the secret from the currently valid kubeconfig
and re-applies the ProviderConfig. There is no separate "update" path; the
same command handles first registration and re-registration after
re-bootstrap. This directly retires the stale-secret trap: the documented
remedy is "run the registration again."

### 3. Responsibility on re-bootstrap

**The cluster owner re-registers.** Whoever re-bootstraps a workload cluster
is responsible for re-running the registration immediately afterwards, as
part of the bootstrap checklist — not the ok-mgmt operator, who has no signal
that the cluster's identity changed.

If the cluster owner has no direct access to ok-mgmt (e.g. ok2-rmf), the
owner hands the new kubeconfig to an ok-mgmt operator, who runs the
registration. The responsibility to *trigger* re-registration stays with the
cluster owner either way.

### 4. Registration is a separate, explicit step

Registration is **not** part of `make bootstrap`. It remains an explicit
opt-in target, consistent with the opt-in Makefile pattern (`install-storage`,
`install-ingress`, ...). Rationale:

- Different blast radius and different kubeconfig context: bootstrap acts on
  the workload cluster; registration writes into ok-mgmt (shared
  infrastructure). Coupling them would let a routine workload-cluster rebuild
  silently mutate the management plane.
- Different actors: a cluster owner may bootstrap without holding ok-mgmt
  credentials (see §3).
- Not every cluster must be managed by ok-mgmt; registration is what makes a
  cluster part of the platform, and that should be a deliberate act.

### Reference implementation (non-normative, after ADR commit)

This ADR defines the contract, not the tooling. The Make target below is the
first implementation; any future mechanism (GitOps, controller, API) may
replace it as long as it fulfills the same contract.

`make register-cluster CLUSTER=<name> [KUBECONFIG_SRC=<path>]` in ok-cluster:

1. Validate the source kubeconfig (`kubectl --kubeconfig ... get nodes`
   against the workload cluster) — fail fast on a dead config.
2. `kubectl create secret generic <cluster>-kubeconfig -n crossplane-system
   --from-file=kubeconfig=... --dry-run=client -o yaml | kubectl apply -f -`
   (against ok-mgmt).
3. Apply the provider-helm `ProviderConfig <cluster>` (templated manifest).
4. Verify: ProviderConfig exists and a probe Release/`kubectl` check against
   the target succeeds.

`KUBECONFIG_SRC` defaults to the conventional talosctl/clusterctl output path
for `<cluster>`. The target must be safe to run repeatedly (§2).

## Consequences

- Registration becomes the **single supported entry point** for introducing
  a workload cluster into the OpenKubes management plane.
- Any future registration mechanism (GitOps, controller, operator) MUST
  preserve the naming contract defined here; a controller's behavior never
  becomes the contract.
- Deployment guide step 5 (DE + EN, Confluence page 3105554433) is replaced
  by a single command; the guide documents the contract and the
  re-registration rule instead of manual kubectl steps.
- Compositions gain a stable, documented `providerConfigRef` convention;
  OK-60 (OpenRMF XRD) builds on it without inventing names.
- A future deregistration path (`make unregister-cluster`?) is out of scope
  here but constrained by this naming contract.
- **Out of scope, deliberately:** ClusterClass (reproducible cluster
  *creation*) and a registration operator (automated
  rotation/status/deregistration) are the next maturity levels and belong in
  a future ADR-014 (Workload Cluster Lifecycle Contract). ADR-013 stays small:
  it answers only "how does a cluster register with the platform."

## Alternatives considered

- **Registration inside `make bootstrap`:** rejected — couples workload
  cluster lifecycle to write access on shared management infrastructure and
  hides a management-plane mutation inside a routine rebuild (§4).
- **Crossplane-managed registration (Observe/Import of kubeconfigs):**
  rejected for now — adds machinery for two clusters; revisit if cluster
  count grows or GitOps (OK-58/ADR-011) takes over ProviderConfig lifecycle.
- **Per-provider secret names (`<cluster>-helm-kubeconfig`, ...):** rejected —
  one credential source per cluster keeps rotation and re-registration
  single-step.

## References

- ADR-Platform-001 (contracts over components)
- OK-61 (this work), OK-60 (first consumer: ok2-rmf / OpenRMF)
- Deployment guide, Confluence page ID 3105554433 (step 5)
