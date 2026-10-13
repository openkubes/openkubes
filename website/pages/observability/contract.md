# Observability Capability Contract

**A cluster is not observability-ready until the applicable capability guarantees pass their contract gate.**

The v1 contract defines five independently meaningful guarantees.

| # | Guarantee | Expected behavior |
| --- | --- | --- |
| 1 | **Metrics** | Declarative workload registration via ServiceMonitor/PodMonitor semantics, with platform components scraped by default |
| 2 | **Dashboards** | Grafana reachable within the cluster, with pre-provisioned platform dashboards |
| 3 | **Logs** | Container logs collected under the declared policy and searchable through the cluster-local backend |
| 4 | **Alerting** | Alerts deliverable to a cluster-defined receiver |
| 5 | **Autonomy** | The observability stack remains functional without cross-cluster connectivity |

The contract is verified by the [source-owned contract test](https://github.com/openkubes/ok-observability/blob/main/tests/contract-test.sh). Implementation and testing evidence are maintained by [`ok-observability`](https://github.com/openkubes/ok-observability).

## Interpret the gate correctly

Per [ADR-Platform-027](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-027-observability-gate-assurance-scope.md), the current gate checks **control-plane-mediated reachability**. A green result does **not** establish healthy pod-to-pod routing, service discovery or cluster DNS.

Before accepting a conformance result, the caller must separately establish CNI/pod-network health. A result from a cluster with degraded CNI health is not valid conformance evidence and must be repeated after network recovery.

Alerting evidence may also be weaker when a receiver-capture endpoint is unavailable: distinguish an alert that **fired** from one whose **delivery** was verified. Do not silently reinterpret the weaker result as full end-to-end evidence.

## Change governance

The five guarantees are governed by [ADR-Platform-018](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-018-observability-capability.md); changes to their meaning require an architecture decision rather than an incidental implementation PR.

[Back to OK Observability](index.md)
