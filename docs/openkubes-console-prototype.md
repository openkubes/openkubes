# OpenKubes Console prototype

The first curated OpenKubes Platform Console lives in [`../console/`](../console/).
It implements the GO decision from OK-151 and preserves the architecture seams from
ADR-Platform-036 without connecting to a live backend.

## Included product areas

- Platform Overview
- Clusters and Cluster Detail
- Workloads / Workload Claims
- Capabilities
- Evidence & Audit
- Create Cluster review journey
- Cluster-scoped diagnostic Shell with read-only command simulation and AI explanations

The UI places `ok-mgmt` first as the Management Plane, uses the OpenKubes visual
identity, and links every displayed readiness assertion to visible evidence.
After selecting a cluster, **Open Shell** demonstrates the future secure session UX
without connecting to a cluster. Mutating commands fail closed, and AI explanations
only propose reviewable read-only diagnostics.

See the [prototype README](../console/README.md) for local use, verification, and
explicit safety boundaries.
