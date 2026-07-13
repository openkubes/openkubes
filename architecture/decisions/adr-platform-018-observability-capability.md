# ADR-Platform-018: Observability Capability — Per-Cluster Stack

**Status:** Accepted
**Date:** 2026-07-13
**Relates:** ADR-Platform-001 (Contracts over components), ADR-Platform-009 (Storage), ADR-Platform-010 (Ingress / access), ADR-Platform-011 (GitOps delivery), ADR-Platform-012 (Air-gapped image mirroring), ADR-Platform-013 (Cluster registration), ADR-Platform-014 (Constrained edge implementation profile), ADR-Platform-017 (Constraint Envelopes)

## Context

Every OpenKubes cluster needs to be observable: metrics, dashboards, and log search. Until now, observability has been implicit — clusters were provisioned without any platform-level guarantee that their state can be inspected.

Two paths were considered:

1. **Centralized observability** — a single stack on ok-mgmt, with workload clusters shipping metrics via remote-write and logs via forwarders.
2. **Per-cluster observability** — every cluster carries its own stack.

The forcing consumers exist today: ok-mgmt, ok1-talos, and the external cluster ok2-rmf all require observability. Per the platform precedent, a second consumer forces the contract.

## Decision

**Every OpenKubes cluster runs its own observability stack: Prometheus, Grafana, and OpenSearch.**

This is a Capability with a Contract, following the established chain:

### Capability

Observability — metrics collection, visualization, and log search, available per cluster.

### Contract (Observability Capability Contract v1)

An OpenKubes cluster is considered successfully provisioned only after the following observability guarantees have been verified:

1. **Metrics:** Workloads can declaratively register for metrics collection (`ServiceMonitor` / `PodMonitor` semantics). Platform components are scraped by default.
2. **Dashboards:** A Grafana instance is reachable inside the cluster, pre-provisioned with platform dashboards.
3. **Logs:** Platform and workload container logs are collected according to the cluster's declared logging policy and are searchable through the cluster-local log backend. The default policy collects all container logs; exclusions and retention are Provider Values.
4. **Alerting:** Alerts can be delivered to a cluster-defined receiver endpoint.
5. **Autonomy:** The stack functions without connectivity to any other cluster. No cross-cluster dependency, no remote-write requirement. This preserves air-gapped operation (ADR-012) and removes ok-mgmt as a single point of failure for observability.

What the contract deliberately does **not** cover:

- Long-term / cross-cluster metric aggregation (federation is a possible future capability, not part of v1)
- Tracing and profiling (out of scope for v1; the contract may be extended, not broken, to add them)
- OpenTelemetry as a collection standard: v1 guarantees Prometheus scrape semantics and policy-based log collection, but does not guarantee native OTLP ingestion. Workloads that expose telemetry exclusively via OTLP require an additional collector or protocol bridge outside the v1 contract. An OTLP ingestion guarantee — implemented through a Collector-based pipeline feeding the same backends — is the designated path for a future contract extension. It would extend the contract rather than break it and would also provide the natural foundation for adding tracing.
- Specific chart versions, storage class names, LB addresses — these are Provider Values

### Implementation Profile (v1)

`ok-observability-standard`:

- kube-prometheus-stack (Prometheus, Alertmanager, Grafana, kube-state-metrics, node-exporter)
- OpenSearch + log collector

Deployment integrates with the ok-cluster lifecycle: a cluster created via `make new` receives the stack as part of provisioning, analogous to `install-storage`. The stack is delivered via the GitOps layer (ADR-011) once ArgoCD is standard; until then, via the ok-cluster Makefile path.

Ownership follows the established storage pattern: the capability's assets (charts/kustomizations, Grafana provisioning, dashboards, Prometheus rules, Alertmanager config, OpenSearch templates, index lifecycle policies, contract tests, documentation) are owned by the capability repository; ok-cluster consumes the capability during provisioning but does not own it.

### Provider Values

- `storageClass` (backed by the ok-storage contract, ADR-009)
- Retention (metrics / logs), envelope-scoped
- Resource requests/limits, envelope-scoped
- Alert receiver endpoint
- Ingress / access configuration (per ADR-010)

## Rationale for OpenSearch over Loki

The obvious CNCF-default choice for logs would be Loki. OpenSearch is chosen deliberately: full-text search and query capabilities over logs are a hard requirement, and OpenSearch also serves as the search backend for adjacent platform consumers (e.g. OpenRMF in the ok2-rmf context). Reusing one search backend for platform logs and adjacent search-oriented consumers reduces operational duplication compared with operating separate Loki and OpenSearch stacks.

This is an Implementation Profile decision, not a Contract clause — the contract requires "logs are collected and searchable", not OpenSearch specifically. A future constrained profile may substitute a lighter backend without amending the contract.

## Constraint Envelope Clause

The guarantee "every cluster" interacts with the `ok-edge-constrained` envelope (ADR-014/017). OpenSearch's resource footprint is likely incompatible with constrained edge nodes.

Resolution principle: **constraint envelopes may substitute the reference implementation with a profile-specific variant without changing the contract.** An envelope-scoped variant may e.g. replace OpenSearch with a lighter log backend, or — where a guarantee cannot be met within the envelope — declare an envelope-scoped reduction (per ADR-017, reductions are legitimate if declared, not silent).

**Open item, to be resolved by amendment before the constrained edge implementation profile can be accepted:** the concrete `ok-edge-constrained` observability variant and which guarantees it carries.

## Verification (Contract Test)

Untestable contracts are not contracts. The contract is verified per cluster by:

1. Deploy a test workload exposing a synthetic metric
2. Register it declaratively (ServiceMonitor)
3. Verify metric ingestion in Prometheus
4. Verify the metric is visible via Grafana datasource query
5. Emit a synthetic log line; verify it is searchable in OpenSearch
6. Trigger a synthetic alert; verify delivery at the configured receiver

This test becomes part of the cluster lifecycle verification, alongside the existing workflow checks. **A cluster is not considered fully provisioned until the observability contract test passes.**

## Consequences

- Every cluster pays the resource cost of its own stack. This is accepted in exchange for autonomy and air-gap compatibility.
- The ok-cluster provisioning workflow gains a readiness gate: `make new` (or its GitOps successor) is complete only when the observability contract test passes. This changes the semantics of "provisioned" from "Kubernetes API available" to "platform guarantees verified".
- **Repository structure (consequence, not core decision):** a new sibling repository `openkubes/ok-observability` owns the capability — contracts, implementation assets (charts, dashboards, Prometheus rules, Alertmanager config, OpenSearch templates, index lifecycle policies), profiles, contract tests, and documentation. This follows the ok-storage precedent: ok-cluster installs and integrates the capability during provisioning but does not own its assets. The core decision above ("every cluster provides a local observability capability") remains valid independently of how repositories are cut in the future.
- ADR-014's edge profile gains a dependency: its observability variant must be defined before the constrained edge implementation profile can be accepted.
- The cluster registration contract (ADR-013) is unaffected; observability is cluster-internal.
