# ADR-Platform-008: Management Cluster as a dedicated cluster type in ok-cluster

**Date:** 2026-07-02
**Status:** Accepted

---

## Context

ok-cluster currently supports two cluster types: `ubuntu` and `talos`. Both are workload cluster types — they produce a Kubernetes cluster ready to run developer workloads, but they do not install any platform tooling (Crossplane, CAPI providers, ArgoCD).

ok-mgmt is a different kind of cluster. It is not a workload cluster — it is the management plane that operates all other clusters. After bootstrapping a Talos cluster, ok-mgmt needs additional software installed automatically:

- Crossplane (platform API engine)
- CAPI + CAPK providers (cluster lifecycle)
- XRDs + Compositions (platform contracts from openkubes/openkubes)
- ArgoCD (GitOps bootstrap — Phase 2)

The question is: where does the automation for this post-bootstrap installation live, and how does an operator express the intent "I want a management cluster, not a workload cluster"?

Three options were considered:

1. **ok-cluster Makefile target** — `make install-crossplane CLUSTER=ok-mgmt`
2. **openkubes/openkubes Makefile** — `make setup` (already exists in capi-platform-v4.2)
3. **Dedicated cluster type in ok-cluster** — `TYPE=talos-mgmt`

---

## Decision

> A management cluster is expressed as a dedicated cluster type in ok-cluster: `TYPE=talos-mgmt`. When `make new CLUSTER=ok-mgmt TYPE=talos-mgmt` is run, ok-cluster scaffolds and bootstraps a Talos cluster on ok-infra, then automatically installs the management plane stack (Crossplane, CAPI providers, XRDs, Compositions).

```bash
# Scaffold + bootstrap + install management stack in one workflow
NODE_SELECTOR=ok-infra make new CLUSTER=ok-mgmt TYPE=talos-mgmt WORKERS=2
make bootstrap CLUSTER=ok-mgmt

# Result: ok-mgmt is ready to provision workload clusters via Crossplane Claims
make deploy cluster=ok1-talos  # (via capi-platform-v4.2 Makefile on ok-mgmt)
```

The `TYPE=talos-mgmt` type shares the same Talos OS profile and CAPI templates as `TYPE=talos` — the difference is the post-bootstrap installation step.

---

## Rationale

**1. Follows the profile pattern established by ok-linux.**
ok-linux uses profiles to express node type intent (`profile: kubevirt`, `profile: gpu`). ok-cluster should use types to express cluster intent. `TYPE=talos-mgmt` is the cluster equivalent of `profile: kubevirt` — a declarative intent that drives a complete, reproducible setup.

**2. Single entry point, reproducible management cluster.**
If ok-mgmt needs to be recreated (ADR-Platform-007 bootstrap paradox), an operator runs the same two commands regardless of when or why the recreation happens:
```bash
NODE_SELECTOR=ok-infra make new CLUSTER=ok-mgmt TYPE=talos-mgmt WORKERS=2
make bootstrap CLUSTER=ok-mgmt
```
No tribal knowledge about "which Helm chart to install in which order" — the type encodes that knowledge.

**3. Clean separation of concerns.**
- `TYPE=talos` — workload cluster, no platform tooling
- `TYPE=talos-mgmt` — management cluster, full platform stack
- `TYPE=ubuntu` — workload cluster, kubeadm-based

ok-cluster does not need to know what Crossplane is or what XRDs to apply. It delegates to a `bootstrap-mgmt.sh` script that encodes the management stack installation — analogous to how `bootstrap.sh` encodes the Talos bootstrap sequence today.

**4. Avoids fragmentation across Makefiles.**
Option A (ok-cluster Makefile target) would spread management cluster concerns across multiple explicit steps — `make bootstrap`, then `make install-crossplane`, then `make setup-xrds`, etc. An operator must know and run them in the right order. Option B (openkubes/openkubes Makefile) requires switching repositories mid-workflow. `TYPE=talos-mgmt` keeps the entire workflow in ok-cluster where cluster lifecycle already lives.

---

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| `make install-crossplane CLUSTER=ok-mgmt` in ok-cluster | Fragmented workflow — operator must know which steps to run after bootstrap; not reproducible as a single intent |
| `make setup` in openkubes/openkubes | Requires switching repos mid-workflow; XRDs and Compositions are platform contracts, but their installation is a cluster lifecycle step |
| Manual installation (no automation) | Not reproducible; violates "idempotent re-create" requirement from ADR-Platform-007 |

---

## Implementation

`TYPE=talos-mgmt` introduces:

```
ok-cluster/
├── templates/
│   ├── talos/          ← existing workload cluster templates
│   ├── talos-mgmt/     ← new: management cluster templates
│   │   ├── cluster-base.yaml.tpl     (same as talos/)
│   │   ├── cluster-v2.yaml.tpl       (same as talos/)
│   │   ├── bootstrap.sh.tpl          (same as talos/)
│   │   └── bootstrap-mgmt.sh.tpl     ← new: installs platform stack
│   └── ubuntu/
```

`bootstrap-mgmt.sh` (generated from template) installs in order:

1. Crossplane (Helm)
2. Crossplane CAPI Provider
3. Crossplane KubeVirt Provider (CAPK)
4. XRDs + Compositions from openkubes/openkubes
5. RBAC + Namespace for platform operations

The XRDs and Compositions are fetched from the openkubes/openkubes repository (GitHub raw URL or local sibling checkout — same pattern as ok-linux profile resolution in ADR-004).

---

## Current state vs. target state

**Today (manual — where we are now):**
```bash
NODE_SELECTOR=ok-infra make new CLUSTER=ok-mgmt TYPE=talos WORKERS=2
make bootstrap CLUSTER=ok-mgmt
# then manually:
helm install crossplane ...
kubectl apply -f xrd.yaml
kubectl apply -f composition.yaml
...
```

**Target (TYPE=talos-mgmt):**
```bash
NODE_SELECTOR=ok-infra make new CLUSTER=ok-mgmt TYPE=talos-mgmt WORKERS=2
make bootstrap CLUSTER=ok-mgmt
# done — ok-mgmt is fully operational
```

The manual path is acceptable today while `TYPE=talos-mgmt` is being implemented. ok-mgmt is already running and functional — this ADR documents the target automation, not a blocker for current work.

---

## Consequences

**Positive:**
- ok-mgmt is recreatable with two commands — no additional operator knowledge required
- Cluster type is self-documenting: `TYPE=talos-mgmt` immediately communicates intent
- Same tool (`make`) for both workload and management cluster lifecycle
- Extends naturally: `TYPE=talos-mgmt-shadow` for ok-mgmt-shadow in the future

**Negative / trade-offs:**
- `bootstrap-mgmt.sh` must be kept in sync with the actual management stack versions (Crossplane, CAPI providers)
- Adds a new cluster type to ok-cluster — more templates to maintain
- `bootstrap-mgmt.sh` has an implicit dependency on openkubes/openkubes for XRDs/Compositions (same sibling-repo pattern as ok-linux, but a new dependency for ok-cluster)

**Neutral:**
- ok-mgmt is already running today (bootstrapped manually with `TYPE=talos`) — this ADR describes the future automation; ok-mgmt does not need to be recreated to benefit from it

---

## Re-evaluation triggers

- ArgoCD added to ok-mgmt → add to `bootstrap-mgmt.sh` installation sequence
- ok-mgmt-shadow implemented → consider `TYPE=talos-mgmt-shadow` or a `ROLE=shadow` flag
- Crossplane version upgrade → update `bootstrap-mgmt.sh` template
