# OK Observability — Evidence-Driven Cluster Visibility

**Metrics. Dashboards. Logs. Alerts. Verified per cluster.**

OK Observability is the OpenKubes **Observability Capability**, defined by [ADR-Platform-018](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-018-observability-capability.md). Rather than treating observability as an optional collection of dashboards, OpenKubes defines a testable contract for local cluster visibility.

## Explore OK Observability

| Topic | What you will learn |
| --- | --- |
| [Observability Stack](stack.md) | Reference implementation: Prometheus, Grafana, Alertmanager and OpenSearch |
| [Capability Contract](contract.md) | The five mandatory guarantees and their verification boundaries |
| [Installation & Verification](installation.md) | How `ok-cluster` consumes the capability and runs the gated install |

## Contract over components

The **`ok-observability` repository owns** the contract, profiles, charts, dashboards, alert rules and tests. **`ok-cluster` consumes** the capability during cluster operations. Implementation profiles may vary by environment without silently changing the contract.

The standard implementation is designed to work per cluster without cross-cluster connectivity, including environments with restricted or air-gapped networks when their prerequisites are satisfied.

The capability's maintained [repository README](https://github.com/openkubes/ok-observability) reports successful contract-test runs on two independent clusters (`ok-shared` and `ok-robotics`). That evidence demonstrates those deployments, **not universal readiness of every possible cluster or envelope**.

## Architecture and ownership

```text
OpenKubes platform decisions (ADR-Platform-018 / 024 / 027)
                |
                v
ok-observability: capability contract + implementation profiles + tests
                |
                v
ok-cluster: explicit gated install + cluster-specific provider values
                |
                v
Target cluster: metrics + dashboards + logs + alerting
                |
                v
Contract result + bounded evidence
```

Start with the [Observability Capability repository](https://github.com/openkubes/ok-observability) and its [repository guide](https://github.com/openkubes/ok-observability/blob/main/AGENTS.md). The site is an entry point; the source repositories remain authoritative.
