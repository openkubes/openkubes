# OK-141 Happy-Path Evidence Evaluation

Status: **Happy path execution-proven; overall A/B/C/D remains unclassified**

Recorded: 2026-08-20

Baseline: `main` at `6877d3a`

## Scope

This checkpoint updates the OK-141 synthesis after the first successful bounded
`create -> converge -> observe` execution and the subsequent manual runtime
validation. It does not:

- change ADR-030 or ADR-031;
- authorize negative tests, failure injection, deletion, or a management-plane
  outage;
- select a public OpenKubes API or CRD; or
- reinterpret the earlier read-only synthesis or immutable failed receipts.

The disposable Cluster remains running for non-destructive follow-up evidence.

## Bound happy-run result

The complete Happy Run is recorded as `HAPPY-RUN-SUCCEEDED` with these redacted
semantic identities:

| Identity | Digest |
|---|---|
| `R` | `sha256:47bb651f6bc0bdb3a7a567efcd4ca4c776f872a63496fa55c2a6aed77d6fa995` |
| `E` | `sha256:2a849d69e9c64344e907c1bce3bb1abf3d8f77217377081a5be055d62c213300` |
| `P` | `sha256:2956184005f4860607e91672fce82164095dee6ebcbe57e5af883951a199c427` |
| `FixtureDigest` | `sha256:438a6882d8e22b644c826cb0a6f2856850afd7c7ef71badb44cd66e8db0393ec` |
| Final redacted summary | `sha256:8945f0c0e84605e432d012ddaef7eb1c7aeac40e6de2899c55e15b74efd592ae` |

The full redacted closure record is retained in
[openkubes/ok-cluster PR #255](https://github.com/openkubes/ok-cluster/pull/255).
Raw API objects, endpoints, credentials, kubeconfigs, UIDs, resourceVersions,
logs, and capability output are excluded.

## What execution proved

The bounded Runner completed the intended chain:

```text
bound fixture R/E/P
  -> authorized staged execution
  -> CAPI and provider convergence
  -> workload Cluster and Nodes
  -> CAAPH / Cilium convergence
  -> NetworkReady evidence
  -> Argo CD platform convergence
  -> PlatformReady evidence
  -> aggregate evidence and immutable receipts
```

This proves the Happy Path for the selected DEV fixture:

- a bounded, non-authoritative Executor can submit the exact desired state;
- CAPI and the provider controllers can own Cluster and Machine lifecycle;
- CAAPH/Helm and Cilium can own Enablement and network convergence;
- Argo CD can own Platform convergence at the exact bound source revision;
- a bounded evaluator can correlate `R`, `E`, `P`, source observations, and
  capability evidence without repairing their resources; and
- failed evaluation evidence can remain immutable while a separately authorized,
  digest-bound retry produces a distinct successful receipt.

The run did not reveal OpenKubes-specific drift that requires a new continuously
running OpenKubes lifecycle controller.

## Manual post-run validation

The live disposable Cluster was checked read-only after closure:

| Area | Observation | Result |
|---|---|---|
| Nodes | control-plane and worker both `Ready` | `PASS` |
| Cilium | DaemonSet 2/2; operator 1/1; sampled Pods running without restarts | `PASS` |
| Storage | default `local-path` StorageClass present; four sampled Observability PVC/PV pairs `Bound` | `PASS` |
| Observability | sampled Grafana, OpenSearch, Prometheus, Alertmanager, operator, exporters, and log collector running | `PASS` |
| Platform | all three required Argo CD Applications `Synced/Healthy` at the exact bound revision | `PASS` |
| Pod failures | no non-running/non-succeeded Pods observed cluster-wide | `PASS` |
| Local credential | workload kubeconfig retained locally with mode `0600` | `PASS` |

These observations are a bounded health snapshot, not a long-term availability or
HA claim.

## Updated architecture assessment

```text
Happy Path create/converge/observe:  PASS
RequiresReconciler:                  none proven
Leading hypothesis:                  A, strongly confirmed for Happy Path
Persistent Status Adapter:           not proven necessary
Broad OpenKubes Operator:            not justified
Overall OK-141 A/B/C/D:              unclassified
ADR-030:                              Proposed
ADR-031:                              separate
```

### A

A is now execution-supported for the Happy Path, not merely documented or
offline-feasible. Existing authoritative controllers performed all corrective
convergence while the OpenKubes Runner remained bounded and receipt-driven.

A is not yet the final overall OK-141 result because the experiment has not proven
the required fail-closed behavior under all negative, controlled mechanism-failure,
delete, and management-outage scenarios.

### B

No real consumer forced a continuously updated OpenKubes status API during the
Happy Run. The bounded evaluator and durable receipts were sufficient. B remains a
future re-evaluation path only if a concrete Watch, policy, alerting, or external
automation consumer proves continuous publication requirements.

### C

The Happy Run provides no evidence for a new OpenKubes-owned lifecycle reconciler.
CAPI, CAAPH/Helm, Cilium, and Argo CD retained their respective ownership. The
Runner observed and correlated their results rather than becoming a second owner.

### D

D remains the rejection boundary. Any follow-up implementation that repairs CAPI,
Cilium, Helm, or Argo-owned resources from an OpenKubes aggregation component must
be rejected or have its ownership boundary redesigned.

## Remaining evidence sequence

The next steps remain deliberately ordered from least invasive to most invasive.

### 1. Non-destructive negative tests

- rejected authorization;
- stale generation or stale evidence;
- duplicate submission and idempotency;
- Executor restart/resume from immutable receipts; and
- incorrect `R`/`E`/`P` correlation failing closed.

These tests must not mutate unrelated resources or broaden authority.

### 2. Controlled mechanism failures

- Enablement or `NetworkReady` failure; and
- Platform or `PlatformReady` failure.

The required proof is that the Runner observes and reports the authoritative
failure without repairing Cilium, Helm, or Argo resources as a competing owner.

### 3. Delete test

Deletion remains a separately authorized test. It must remove the Argo target
binding first, then use CAPI-owned Cluster deletion, verify provider/VM/RBAC/Secret/
Namespace closure, and remove the privileged provider-access Secret last. Force
Delete and finalizer manipulation remain prohibited.

### 4. Management-plane outage

The outage scenario remains `NO-GO` until its own preflight binds the observer,
recovery path, and accepted DEV recoverability boundary. ADR-031 authority and
fencing remain separate from ADR-030 execution ownership.

## ADR consequence

ADR-030 remains `Proposed`. If hypothesis A also survives the remaining scenarios,
the ADR should be revised before acceptance to:

- make the aggregate-result invariant normative while allowing a bounded evaluator
  unless a forcing consumer proves a persistent adapter necessary;
- describe Enablement and Platform convergence as existing-controller ownership;
- preserve single-writer ownership and fail-closed revision correlation; and
- keep ADR-031 authority, fencing, and disaster recovery separate.

No ADR change is made by this checkpoint.
