# OK-141 Controlled Mechanism-Failures Evidence Evaluation v1

Status: **E1 and P1 execution-proven; overall A/B/C/D remains unclassified**

Recorded: 2026-08-20

Baseline: `main` at `5cbe8d6`

## Scope

This checkpoint combines the two separately authorized, executed, restored,
and redacted controlled mechanism-failure scenarios. It makes no ADR change
and authorizes no deletion, outage, retry, cleanup, or further failure
injection.

## Bound evidence

| Scenario | Candidate | Redacted closure | Result |
|---|---|---|---|
| E1 Enablement / `NetworkReady` | `sha256:ca3801cded6747c8f09c92ff9d617c5a61a129244a1f6d385621003c6349231b` | `sha256:76513bf068355e3d26db7174ef27633dc6a2c1dd8d476a7b28313fecc99eb655` | `PASS-FAIL-CLOSED-RESTORED` |
| P1 Platform / `PlatformReady` | `sha256:d66513ecd877dba656f0efb108c7aab1c7c496d0560f0bb65e06d068b1a536d1` | `sha256:3d55cd9eb368302e0116d954da0eb1bd6e2337d90c3ffb3b4508320a6f105369` | `PASS-FAIL-CLOSED-RESTORED` |

Raw API objects, credentials, endpoints, UIDs, resourceVersions, and local
Evidence remain excluded.

## E1 ownership result

The desired Cilium projection was changed to a deliberately invalid version.
The bounded evaluator reported `NetworkReady=False` while the existing Cilium
runtime remained healthy. It did not mutate Cilium or repair CAAPH/Helm. The
exact authorized projection restore returned HCP, HRP, and `NetworkReady` to
the healthy baseline.

```text
desired Enablement convergence  CAAPH / Helm
runtime network truth           Cilium / Kubernetes
OpenKubes runner                observe + correlate + fail closed
OpenKubes package repair        none
```

## P1 ownership result

The dashboards Application was changed to a deliberately absent source path.
Argo CD reported the current manifest-generation failure and the evaluator
reported `PlatformReady=False`. Core and Alerting remained healthy, and the
existing dashboard data remained unchanged. The runner did not mutate target
Platform resources. The exact Application restore returned the three required
Applications to `Synced/Healthy` at the bound revision.

```text
desired Platform convergence   Argo CD
Platform status truth          Argo Application status
OpenKubes runner               observe + correlate + fail closed
OpenKubes Platform repair      none
```

## Combined necessity result

Both scenarios demonstrate that fail-closed aggregate evaluation does not
require the evaluator to become a second lifecycle owner. Existing controllers
retain corrective convergence responsibility. The bounded runner needs exact
projection authority only for the authorized experiment and exact restore; it
does not acquire ongoing repair ownership.

```text
RequiresReconciler:             none proven
Broad OpenKubes Operator:       not justified
Persistent Status Adapter:      not proven necessary
Controlled mechanism failures: PASS
```

## A/B/C/D assessment

### A

A is now strongly execution-supported across the Happy Path, non-destructive
negative controls, and both controlled mechanism failures. A remains the
leading hypothesis rather than the final overall classification until the
separately gated Delete and management-outage evidence is reviewed.

### B

Neither scenario produced a forcing consumer for continuously published
OpenKubes status. B remains unproven. A later concrete Watch, policy, alerting,
or external-automation requirement may trigger re-evaluation.

### C

Neither scenario revealed OpenKubes-specific desired-state drift requiring a
new durable corrective loop. C is not supported by the controlled-failure
evidence.

### D

D remains the rejection boundary. An OpenKubes component that repairs CAAPH,
Helm, Cilium, Argo, or their target resources would duplicate the ownership
demonstrated by these executions.

## Remaining evidence

1. **Delete test:** separately authorize removal of the GitOps target binding,
   CAPI-owned Cluster deletion, provider/VM/RBAC/Secret/Namespace closure, and
   terminal Evidence retention. No Force Delete or finalizer manipulation.
2. **Management-plane outage:** remain `NO-GO` until a separate preflight binds
   the observer, exact outage action, recovery path, and accepted DEV
   recoverability boundary. ADR-031 authority and fencing stay separate.

## Current classification

```text
Happy Path:                    PASS
Non-destructive negatives:    PASS
Enablement failure E1:        PASS-FAIL-CLOSED-RESTORED
Platform failure P1:          PASS-FAIL-CLOSED-RESTORED
Delete:                       NOT GRANTED
Management outage:            NOT GRANTED

Overall OK-141 A/B/C/D:       unclassified
Leading hypothesis:           A, strongly execution-supported
RequiresReconciler:           none proven
ADR-030:                       Proposed
ADR-031:                       separate
```

No ADR status or public API decision is changed by this checkpoint.
