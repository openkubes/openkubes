# The OpenKubes Family

> The mother owns the contracts, not the components. The children do the work.

![The OpenKubes Family](openkubes-family.svg)

## How to read this diagram

OpenKubes is not one repository — it is a **family of repositories**, each owning exactly one capability contract.

### The mother: `openkubes/openkubes`

The mother implements nothing. She holds the family together by owning everything that is *shared*:

- **Contracts & constitution** — every architectural decision lives here as an ADR
  ([ADR-Platform-001](../architecture/decisions/ADR-Platform-001-contracts-not-components.md)
  is the family rule itself), together with the capability contracts between the
  layers and the Crossplane XRDs & Compositions that make them consumable.
- **Memory** — the [knowledge graph](knowledge-graph.html) is derived directly
  from Git: ADRs, components, capabilities, issues, and commits, rebuildable at
  any time with `okgraph.py build`. This is the first implementation of
  *Immortal Mind, Layer 1*: memory lives in Git; tools and models are disposable.
- **Bootstrap** — the platform reference implementation, including the 8-step
  `bootstrap-mgmt.sh` that brings up a management cluster from zero.

### The children: one capability each

| Repository | Capability | Current implementation |
|---|---|---|
| [`ok-linux`](https://github.com/openkubes/ok-linux) | **Host OS** — tells every node which OS it runs | Talos Linux (version, schematic ID, `machineconfig.yaml`) |
| [`ok-cluster`](https://github.com/openkubes/ok-cluster) | **Cluster Lifecycle** — creates and operates clusters | CAPI · CAPK · Crossplane · Cilium · Traefik |
| `ok-storage` | **Storage** — persistent volumes as a platform capability | Longhorn, three storage classes |
| `ok-gitops` | **GitOps** — reconciliation of desired state | Argo CD |
| `ok-apps` | **Applications** — what the platform is for | Open WebUI, Ollama, your workloads |

### The two kinds of arrows

- **Gold, dashed (mother → child):** the mother *defines the contract* each
  child must honour. The child chooses how.
- **Grey, solid (child → child):** each layer *consumes only the contract of
  the layer directly below it* — never its implementation. Example: `ok-cluster`
  reads the Talos version and schematic ID from `ok-linux`; it does not decide
  them.

### Why a family, not a monorepo?

Because contracts outlive implementations. Talos, CAPI, Longhorn, and Argo CD
are all replaceable — as long as the replacement honours the same contract, no
other family member changes. The mother makes that possible by being the one
place where contracts (and the decisions behind them) are recorded, reviewed,
and remembered.

Bare metal sits *outside* the family: the infrastructure provider hosts the
family, but is itself just another swappable implementation detail.

---

*See also: [the pizza analogy](pizza-capability-contracts-explained.md) for a
newcomer-friendly take on capability contracts, and
[the platform architecture diagram](openkubes_platform_architecture.svg) for
the technical systems view.*
