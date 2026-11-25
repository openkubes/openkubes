# OpenKubes Tutorials

Hands-on guides for developers, platform engineers and contributors building
with OpenKubes.

## Getting started

### Getting Started with OpenKubes OK CLI v1.0.1

Install the OK CLI, explore its commands, configure an existing compatible management cluster, and walk through the supported Talos/KubeVirt workload-cluster lifecycle.

- [Read the tutorial](ok-cli-v1.0.1-getting-started.md)
- Requirement: an already prepared Same-Plane Talos/KubeVirt management cluster for live provisioning.
- The tutorial starts with local CLI exploration and a read-only cluster plan; live provisioning is optional and requires explicit authorization.

### AI thinks. OpenKubes executes. Evidence proves. — HITL & HOTL

Reproduce the AI Tinkerers Düsseldorf demonstration on an **existing disposable W-JAX kind lab**: compare exact human approval (HITL) with a local, policy-bounded, explicitly enabled supervisor (HOTL), then inspect the Kubernetes outcome and the different evidence guarantees.

- [Follow the HITL/HOTL recovery tutorial](hitl-hotl-agentic-recovery.md)
- Requires the configured `openkubes/ok-console` W-JAX runtime, dedicated demo credentials, `kubectl`, `kind`, and Ollama.
- **Experimental only:** HOTL evidence is mutable local JSONL and same-process read-back, not independent verification.

## Contributor tutorials

### Build a Local OpenKubes BYOH Development Environment with CAPD

Create an isolated local Cluster API management cluster and a Docker-backed
workload cluster. Learn how CAPI resources map to Kubernetes concepts, how
CAPD provisions machines, how kindnet provides Pod networking, and how the
HAProxy API load balancer connects the workload control plane.

- [Read the tutorial](capd-local-dev-environment.md)
- Platform: macOS with Colima (tested); Intel macOS and Linux validation
  welcomed from contributors.
- Start with `make ok-capd-setup` for the complete local environment.

