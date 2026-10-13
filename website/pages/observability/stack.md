# Observability Stack

The standard implementation profile, `ok-observability-standard`, composes open-source components to satisfy the **Observability Capability Contract v1**.

## Standard implementation

| Area | Reference components | Contract purpose |
| --- | --- | --- |
| Metrics | Prometheus, kube-state-metrics, node-exporter | Collect platform and workload measurements |
| Dashboards | Grafana | Provide cluster-local dashboards and data-source queries |
| Alerting | Prometheus rules, Alertmanager | Route actionable alerts to a configured receiver |
| Logs | OpenSearch and a log collector | Collect and search logs under a declared policy |

The underlying kube-prometheus-stack provides much of the metrics, dashboard and alerting stack. The contract names outcomes, **not permanent product dependencies**. An envelope-specific profile may substitute components while preserving, or explicitly declaring limitations to, contractual guarantees.

## Why local observability?

A local stack can continue operating when connectivity to management or other clusters is unavailable. This is especially relevant to sovereign environments and air-gapped deployments. It also means each cluster must budget for local compute, storage and retention.

OpenSearch is the standard profile's log-search implementation. Its richer search capabilities are an implementation choice, not a required backend in the capability contract.

## Source documentation

- [Reference implementations](https://github.com/openkubes/ok-observability/tree/main/implementations)
- [Profiles](https://github.com/openkubes/ok-observability/tree/main/profiles)
- [Dashboards](https://github.com/openkubes/ok-observability/tree/main/dashboards)
- [Alerting assets](https://github.com/openkubes/ok-observability/tree/main/alerting)
- [ADR-Platform-018](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-018-observability-capability.md)

**Not covered by v1:** Cross-cluster federation or long-term aggregation, tracing, profiling, and native OTLP ingestion. Those require separate implementation or future contract extensions.

[Back to OK Observability](index.md)
