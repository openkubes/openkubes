# Getting Started with OpenKubes

**Your Kubernetes Framework. Built for the Age of AI.**

OpenKubes helps you build your own Kubernetes platform with open, modular components and explicit platform contracts. Choose the path that matches what you want to explore. You do **not** need a bare-metal cluster to start learning.

## Choose your path

| Path | Best for | Start here |
| --- | --- | --- |
| **OpenKubes Local** | Developers evaluating OpenKubes on a Mac | [Run OpenKubes Local](#1-openkubes-local) |
| **OpenKubes Cluster** | Platform engineers exploring cluster lifecycle and infrastructure choices | [Explore OK-Cluster](#2-openkubes-cluster) |
| **AI & Agentic Operations** | Teams running AI workloads and evaluating future agent-assisted operations | [Explore AI capabilities](#3-ai-and-agentic-operations) |

## 1. OpenKubes Local

**Recommended first step if you are new to OpenKubes.**

[OpenKubes Local](https://github.com/openkubes/ok-local) provides a development environment with separate management and infrastructure/workload Kubernetes clusters on **macOS using Multipass and K3s**. The accompanying tutorials introduce KubeVirt, Cluster API and Crossplane.

Before starting, review the [local prerequisites](../docs/ok-local/tutorial-prerequisites.md).

```bash
git clone https://github.com/openkubes/ok-local.git
cd ok-local
make setup
```

The setup requires the tools and host resources described in the repository. Once it finishes, use `make help` and the [OK Local tutorials](https://github.com/openkubes/ok-local/tree/main/docs) to continue with cluster access, KubeVirt, CAPI and Crossplane.

[OpenKubes Local README →](https://github.com/openkubes/ok-local#readme)

## 2. OpenKubes Cluster

**For infrastructure and platform engineers.**

[OK-Cluster](https://github.com/openkubes/ok-cluster) is the OpenKubes cluster-lifecycle engine. Its scope includes declarative cluster creation, observation and upgrades across supported infrastructure and OS paths. It is not a one-command replacement for the local tutorial: cluster creation requires explicit environment inputs, operator review and authorization.

Start with the [OK-Cluster README](https://github.com/openkubes/ok-cluster#readme), then consult the [operator runbook](https://github.com/openkubes/ok-cluster/blob/main/docs/ok147-operator-runbook.md) before attempting any live cluster operation.

For an initial, **offline, non-mutating** exploration, the repository documents:

```bash
git clone https://github.com/openkubes/ok-cluster.git
cd ok-cluster
make ok-cli-build
.tools/bin/ok cluster create --help
```

This builds and inspects the CLI; it does not provision a cluster. For runtime requirements and supported workflows, follow the repository documentation rather than copying old bare-metal installation commands.

[Explore OK-Cluster →](https://github.com/openkubes/ok-cluster)

## 3. AI and Agentic Operations

**For AI workloads, AI-enabled platform operations and future agent integrations.**

OpenKubes distinguishes **running AI workloads on Kubernetes** from **using AI agents to propose or coordinate infrastructure operations**. Agentic Operations is an evolving, optional capability: policy checks, explicit authorization, reconciliation and evidence remain essential. Do not assume autonomous production operations are available as an out-of-the-box installation.

Start with the [Agentic Operations Reference Architecture](../agentic-operations-reference-architecture.md) and the [OpenKubes architecture overview](../architecture/).

We will link a dedicated AI installation guide here once its source repository and supported entry points are confirmed.

## Where to go next

- [Developer documentation](../docs/) — documentation collected from OpenKubes repositories.
- [Features](../features/) — capabilities of the framework.
- [Architecture](../architecture/) — design principles, platform contracts and boundaries.
- [GitHub organization](https://github.com/openkubes) — repositories, issues and contributions.

> **Source of truth:** This page lives in [`openkubes/openkubes/docs/getting-started/README.md`](https://github.com/openkubes/openkubes/blob/main/docs/getting-started/README.md). Component-specific setup details remain in their own repositories.
