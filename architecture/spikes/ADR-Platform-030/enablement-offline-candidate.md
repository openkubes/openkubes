# R6 Enablement Offline Candidate

Status: **Offline candidate defined; live convergence unproven**

Recorded: 2026-08-09

## Candidate

The first execution fixture uses the existing `ok-cluster` Talos/KubeVirt Cilium
profile and the chart's own Helm renderer.

```text
profile                    cilium-fixture-v1
chart                      cilium 1.19.6
chart artifact SHA-256     21c43cf53841f9ab0375047d95aa4c64051ea52bbd2c679416e6408f5f1c9179
normalized values SHA-256  a02a2a8b5c5213c86e482ef7421884281d00d3bae1f27c34d67b3726df12d410
semantic E                 7393fdbfd31a6e8122860f4b458540672083e2323f5d1a47a776ff39db836568
```

`E` binds the package artifact, normalized values, rendered immutable image set,
stable target Contract identity, required readiness sources, and owner-candidate
classification. It deliberately does not embed `R`; R8 provides the `R -> E`
correlation and thereby avoids a circular digest definition.

## Existing renderer evidence

`helm template` against the local digest-verified chart and committed values rendered:

```text
objects                 25
rendered YAML digest    262c00448d0fc0cf6cc8166f3efff237946836e9f493600b0d53fb54e6c3599a
object-set digest       eca2e16b5b39815bc429ffb23abbcb3f7945aedaa83e065a7ee7d26707381b3a
```

Kinds:

```text
ClusterRole=2 ClusterRoleBinding=2 ConfigMap=2 DaemonSet=2 Deployment=1
Namespace=1 Role=4 RoleBinding=4 Secret=2 Service=2 ServiceAccount=3
```

All three rendered images carry `@sha256` identities. The harness does not render Helm
objects itself; it validates the semantic profile around output from Helm.

## Ownership

```text
OpenKubes fixture/harness  -> define and verify E
Helm chart                 -> render package resources
CAAPH candidate            -> later own apply/retry/drift for the package
Cilium/Kubernetes          -> own runtime network state
bounded evaluator          -> derive NetworkReady evidence
```

CAAPH remains **configurable, not proven sufficient**. No CAAPH resource is invented
by the harness, because its exact API/configuration must come from the selected
existing mechanism and later review.

## Offline negative controls

Automated tests prove:

- changed normalized values cannot validate against the original E inputs;
- changed chart artifact identity produces a different E;
- missing/non-digest image identity is rejected;
- missing target Contract identity or readiness-source contract is rejected; and
- E calculation performs no package apply.

## R6 boundary

Offline evidence does not prove bootstrap ordering, controller restart/resume, retry,
drift correction, deletion, or that `NetworkReady` follows exact E. Those are
mutation-gated Phase-M claims.

```text
E construction:             deterministic / offline proven
Helm rendering:             existing renderer / offline proven
Immutable package identity: proven for candidate inputs
CAAPH convergence:          configurable / not proven
NetworkReady:               fixture-defined / live proof pending
RequiresReconciler:         none proven
Infrastructure:             NO-GO
```
