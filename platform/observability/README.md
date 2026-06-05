# Observability

> 🔒 **Enterprise Feature**
>
> Full observability stack configuration and managed dashboards are available
> as part of the **OpenKubes Enterprise** subscription or as an add-on for
> community subscribers.
>
> Contact: [kubernauts.de](https://kubernauts.de) or open a discussion on
> [GitHub](https://github.com/openkubes/openkubes/discussions).

---

## Overview

OpenKubes follows a strict separation between platform observability and tenant observability:

| Layer | Scope |
|-------|-------|
| **Platform Observability** | Management cluster, infrastructure health, CAPI controllers |
| **Tenant Observability** | Workload clusters, application metrics, per-tenant dashboards |
| **Security / Audit** | Policy violations, access logs, compliance reporting |

---

## Recommended Stack

| Concern | Technology |
|---------|-----------|
| Metrics | Prometheus + Thanos / VictoriaMetrics |
| Logging | Loki / OpenSearch |
| Tracing | Tempo / Jaeger |
| Dashboards | Grafana |
| Alerting | Alertmanager |
| Audit | Kubernetes Audit Logs + Falco |

---

## Community Baseline

A minimal observability baseline (Prometheus + Grafana) for the Management Cluster
will be documented here as part of the OpenKubes community roadmap.

Contributions welcome — see [CONTRIBUTING.md](../../CONTRIBUTING.md).
