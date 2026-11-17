# OpenKubes authoring Contract v1 — unification proposal

**Status:** Proposed, non-normative until ADR/Contract review and executable conformance  
**Date:** 2026-11-12  
**Issue:** [OK-226](https://kubernauts.atlassian.net/browse/OK-226)  
**Architecture:** [ADR-Platform-034](./ADR-Platform-034-ok-up.md)  
**Code owners:** OK-147 (bounded executor), OK-148 (convergence UX), OK-76 (trusted M2b operator)

## Decision to make

Accept **one versioned, user-authored desired-state representation**, with a **single deterministic canonicalizer** and explicit, versioned *execution-profile projections* downstream. Do not equate a friendly request with a verified, authorized, infrastructure-ready execution plan.

**This document proposes a minimal v1 authoring shape and exact gates, not a finished JSON schema or conversion implementation.** It must not be used to authorize mutations.

## Grounded baseline and incompatibilities

| Existing input | Identity | Topology/network | Execution | Authority |
| --- | --- | --- | --- | --- |
| M2b `cli.openkubes.io/v1alpha1` `ClusterRequest`, profile `talos-kubevirt-reference` | `metadata.name` | Control-plane 1; workers 1–10; **only auto/omitted network allocation**, resolved later by Make | `ok cluster plan/provision`; Same-Plane | Human-reviewed imperative operator execution; **not** ADR-034 Policy/CAS |
| Runner `cli.openkubes.io/v1alpha1` `Cluster`, profile `talos-kubevirt-mvp` | `metadata.name` | Fixed 1 CP + 1 worker, **explicit** endpoint/pod/service CIDR | `ok up` currently aliases `cluster create`; `ok preview` uses this strict parser | Bounded Runner/Authority preparation; may stop awaiting platform approval |
| OK-147 test Contract `test.openkubes.io/v1alpha3` `ClusterIntentFixture` | name **and namespace** | Explicit infrastructure, OS, topology, provider-access, networking, enablement and platform material | Existing Go `internal/contract.Canonicalize` and bounded executor fixtures | Test schema; providerAccess fixture hard-codes distinct `ok-mgmt` and `ok-infra` |
| ADR-034 product `./openkubes.yaml` | One authored cluster per directory | Not yet versioned/accepted | `ok validate/plan/up/status`; `down` later | Independent Policy, single-use claim, atomic CAS and evidence **required** |

Sources: `ok-cluster/docs/ok76-cluster-request.md`, `cmd/ok/cluster_plan.go`, `cmd/ok/cluster_intent.go`, `internal/contract/canonical.go`, `internal/contract/testdata/ok141-contract-v3.schema.json`. The test schema's `managementPlane=ok-mgmt` / `providerPlane=ok-infra` constants **cannot** be used unchanged for Same-Plane.

## Minimal *candidate* human-facing file

```yaml
# EXAMPLE ONLY: proposed shape, not a supported CLI schema.
apiVersion: platform.openkubes.io/v1alpha1 # placeholder pending naming review
kind: Cluster
metadata:
  name: my-first-cluster
spec:
  platformProfile: talos-kubevirt-reference
  topology: same-plane
  controlPlane:
    replicas: 1
  workers:
    replicas: 1
  network:
    allocation: automatic
```

The short human input intentionally does **not** contain kubeconfigs, RBAC grants, public API endpoints, cluster UIDs, storage/PV handles, Golden Image references, arbitrary manifests, or authorization decisions. These must come from separately reviewed, trust-bound platform profiles and observed state. The above `platformProfile` is only a **candidate name**; it does not imply the old M2b `ClusterRequest` accepts this form.

**Version ownership:** Before coding, approve exact `apiVersion/kind`, schema URI, defaults, API stability/deprecation rules, identity/namespace mapping, and whether `topology` is semantic user intent or a pinned platform-profile choice. Do not ship a guessed public API.

## One deterministic translation pipeline

```text
openkubes.yaml
  -> strict parse + reject unknown fields, duplicate YAML keys, aliases, secret content
  -> versioned defaults + schema validation
  -> semantic canonicalization (reuse internal/contract; canonical JSON + revision R)
  -> read authoritative desired revision for exact tenant/cluster/profile
  -> derive CreateCluster | NoOp | UNSUPPORTED (do not infer from observed lag)
  -> resolve explicit platform profile + management/provider identities
  -> allocate/reserve network under **single-writer authority**, before final approval
  -> freeze execution profile inputs and digest-bound plan identity
  -> exact Policy decision + single-use authorization claim
  -> atomic CAS desired-state acceptance
  -> bounded executor -> existing controllers -> independent evidence
```

**Two distinct immutable digests** are expected where unresolved `auto` is supported:
- **Requested revision R:** canonicalized *semantic desired state*. It must not accidentally change because a renderer picked a different IP, a kubeconfig path moved, or a local timestamp changed.
- **Execution binding digest P:** selected provider profile, resolved network, validated target identities, applied versions, images and verified runtime artifact hashes. P is bound to the authorized transition and must be rechecked immediately before mutation. It is never silently recomputed after the user's review.

The exact `R/P` binding method and policy authorization fields require a proof in OK-147/OK-148. The existing Make network inventory is **not an atomic IP reservation**; consequently, a production `ok up` must not promise race-free automatic allocation until it has a shared allocation authority or proves exclusive single-writer control across CLI and direct Make operators.

**No double write:** only the selected Authority Profile owns the desired revision CAS. The profile-specific adapter may prepare a projection; it does not independently become an authority, a second Contract-to-CAPI compiler, or a retry loop.

## First execution profile — Talos/KubeVirt Same-Plane

Required profile validation:

1. Explicitly chosen management and provider identities point to the **same live Kubernetes API** (server identity, CA trust, stable `kube-system` UID) and required controllers/storage are present.
2. A compatible KubeVirt/CAPK/Talos installation and pinned Cilium, image and storage assumptions exist. The workload Kubernetes API remains an independent target identity.
3. The Authority Store, Policy decision service, and bounded Executor have explicit placement, audience, independent least-privilege credentials, durable storage, and a verified CAS implementation in this Same-Plane topology. **The OK-147 `ok-mgmt` Job default is not automatic evidence of Same-Plane compatibility.**
4. The reviewed cluster identity does not already exist as an unmanaged/M2b-provisioned resource. Unknown inventory or name collisions fail closed. Adoption requires a separate authorized operation with UID/ledger provenance; absence of Authority revision alone is insufficient.
5. Evidence of provisioning captures independent source conditions, precise transition and authorization identity, and scoped provider resource identities. The M2b schema-3 original-UID ledger remains required for eventual provider-specific teardown.
6. A single visible `ok up` confirmation is permitted only if all mutable allocation/scaffold choices are finalized before it and post-confirmation checks prove the same immutable bound plan. Otherwise retain a second explicit gate; never quietly change critical values after review.

## Explicitly deferred

- `ok down` and `DeleteCluster`: separate authorization, desired-absence ownership, cleanup and retained ledger, not M2b `cluster destroy` alias.
- `Split-Plane` execution profile, arbitrary provider selection, automatic `ok-mgmt` setup, imported clusters.
- M4 local `kind` bootstrap and CAPI pivot.
- Public beta release until security review, verified binary and relevant QEMU teardown follow-ups.

## Conformance gates for a *future* schema/adapter PR

1. Equivalent YAML documents produce identical R (formatting, field order, explicit defaults); a semantic change changes R.
2. Ambiguous/unknown fields, duplicate keys, aliases, embedded secrets, incorrect apiVersion/kind, unsupported topology/profile and symlinks fail locally.
3. Default lookup reads **only** `./openkubes.yaml`; explicit `--file/-f` resolves to an equivalent R. No parent traversal.
4. Unsupported or missing platform profile and missing/changed management/provider live identities fail before authorization and mutation.
5. `auto` values never generate silent post-approval mutations, changed allocation or fabricated reservations.
6. Only authorized `ABSENT -> R1` may create; unchanged R -> R returns NoOp; lagging observed nodes never trigger Scale.
7. Two concurrent conflicting transitions: one CAS winner; stale predecessor and lost response follow ADR-034.
8. Unknown/existing M2b resource with absent Authority revision does **not** create a duplicate and does not auto-adopt.
9. Absence of Policy/Authority, malformed transition, expired or consumed grant, or incomplete verification has **zero** external mutations.
10. CLI and in-cluster Job use shared canonicalization/authorization/execution implementations; no separate compiler or reconciliation logic.
11. Readiness claims require independently observed correct-generation sources, not `make bootstrap` exit 0.
12. Existing M2b original-UID/schema-3 protections and unrelated Golden Image/storage exclusions remain intact.

## Decision sequence / required approvals

1. Review this proposal with OK-147/OK-148 owners and accept the **single-authority and R/P model**.
2. Freeze an **actual** versioned schema with machine-executable positive/negative fixtures and a documented compatibility strategy for both legacy inputs. No silent migration.
3. Implement **read-only** `ok validate`/authority-aware `ok plan` using the accepted canonicalizer; expose `UNKNOWN_AUTHORITY`, not fictitious Create, when state cannot be read.
4. Prove one Same-Plane Authority Profile and authorized CreateCluster/NoOp end to end before rerouting `ok up`.
5. Keep ADR-034 at `Proposed` until its documented acceptance evidence passes. A merged design PR does not by itself mean `Accepted`.

**Outcome requested:** approve one canonical public authoring language and one execution boundary; preserve the proven M2b lifecycle but do not pretend the existing Make operator commands are already an authorized desired-state engine.
