# Scenario: Management-Plane Outage and Reconciliation Resume

**Status:** Planned — not yet executed
**Decision under test:** ADR-Platform-030
**Forcing profile:** KubeVirt workload cluster managed by CAPI/CAPK on ok-mgmt

## Invariants

> **Loss of the management plane must interrupt lifecycle reconciliation, not the
> runtime availability of otherwise healthy workload clusters.**

> **When management-plane availability is restored, lifecycle reconciliation must
> resume from persisted desired state without requiring the original Executor.**

The first invariant is deliberately bounded. It does not promise survival of a failure
in the infrastructure plane, a workload cluster that has no control-plane or worker
redundancy, or a runtime dependency hosted only on ok-mgmt.

GitOps behavior is profile-dependent:

- an in-workload-cluster GitOps profile must continue reconciling during the outage;
- a centralized ok-mgmt GitOps profile is expected to pause and must resume afterward;
- the evidence must state which profile is under test and must not claim the other
  behavior.

## Why this scenario is required

CAPI `Cluster`, `Machine`, `MachineDeployment`, and `MachineHealthCheck` resources and
their controllers live on the management cluster. Existing workload control planes,
Nodes, and applications are separate. A management outage should therefore freeze
lifecycle reconciliation while otherwise healthy workload runtime continues.

This test proves that boundary and then verifies recovery. It is not a disaster-recovery
test for permanent etcd loss; that belongs to ADR-Platform-031.

## Preconditions

- [ ] The test uses a disposable KubeVirt workload cluster with at least three workers
      and a highly available workload control plane, or the accepted reduced failure
      budget is documented.
- [ ] `Ready=True` and all profile-required Conditions match the current contract
      generation.
- [ ] A continuously probed test application has enough replicas and anti-affinity to
      survive one worker loss.
- [ ] A `MachineHealthCheck` or the selected remediation mechanism is installed and
      proven in the baseline.
- [ ] The desired state, CAPI object graph, resource UIDs, Machine/Node mapping, and
      KubeVirt VM/VMI inventory are captured.
- [ ] The original Executor has terminated before the outage; no lifecycle workflow is
      kept alive to assist recovery.
- [ ] A verified ok-mgmt backup exists outside the ok-mgmt/ok-infra failure domain.
- [ ] Out-of-band access to ok-infra and a tested procedure to restart ok-mgmt exist.
- [ ] No unrelated create, scale, upgrade, or delete operation is active.
- [ ] Fault injection and rollback commands have been reviewed for the exact test
      resources; no wildcard or broad recursive target is allowed.

## Phase 0 — Baseline

Record:

1. contract generation and aggregate Conditions;
2. CAPI/CAPK and MachineHealthCheck status;
3. workload API, Node, Pod, Service, DNS, and application probes;
4. GitOps revision and health;
5. ok-mgmt and ok-infra VM/VMI inventory; and
6. evidence-store reachability independent of ok-mgmt.

Baseline acceptance:

- all required Conditions are `True` for generation N;
- the application probe passes continuously;
- a prior controlled remediation has proved that the configured health mechanism can
  replace a failed worker while ok-mgmt is available.

## Phase 1 — Stop the management plane

Using the reviewed out-of-band procedure, make the ok-mgmt Kubernetes API and all CAPI,
CAPK, Executor, Status Aggregator, and centralized GitOps controllers unavailable while
leaving ok-infra and the workload cluster running.

Record the exact start time and verify from an independent observer that:

- the ok-mgmt API is unavailable;
- existing workload Kubernetes API and application probes continue;
- existing workload VMs and LoadBalancer resources remain present on ok-infra; and
- no lifecycle controller is still active elsewhere.

Do not interpret unreachable aggregate Conditions as new `False` values; record them as
unobservable during the outage.

## Phase 2 — Verify runtime behavior

During a bounded observation window:

- continuously probe the workload API and application;
- create or restart an application Pod and verify workload-local scheduling;
- verify Services, DNS, and the declared data path;
- for in-cluster GitOps, commit or introduce a harmless declared drift and verify
  convergence;
- for centralized GitOps, verify that reconciliation is paused and retain the pending
  revision for the recovery phase.

PASS means runtime behavior matches the profile's declared management dependency. It
does not require lifecycle operations to work while ok-mgmt is unavailable.

## Phase 3 — Inject one worker failure

Use a pre-reviewed, reversible KubeVirt fault that makes exactly one selected workload
Node unavailable without affecting ok-mgmt, ok-infra, the workload control plane, or
other workers. The concrete command is chosen only after confirming the selected CAPK
profile's VM run strategy; a fault that KubeVirt immediately self-recovers does not
test CAPI remediation and is invalid.

Verify while ok-mgmt remains unavailable:

- the target Node becomes unhealthy or unreachable;
- application Pods reschedule to surviving capacity;
- the declared application availability budget is met;
- no replacement CAPI `Machine` or KubeVirt VM appears; and
- the observation window exceeds the configured MachineHealthCheck timeout plus its
  normal reconciliation margin.

Abort if quorum, application data integrity, or the declared single-worker blast radius
is endangered.

## Phase 4 — Restore ok-mgmt

Restore the same persisted ok-mgmt state; do not reconstruct CAPI desired state by
blindly applying rendered manifests. Before unpausing or allowing broad reconciliation:

1. verify API and etcd health;
2. verify expected CAPI/CAPK/provider versions and credentials;
3. compare the restored CAPI object UIDs and desired state with the baseline;
4. inventory external KubeVirt resources and the failed worker; and
5. confirm no second management plane is actively reconciling the same objects.

Then allow reconciliation and verify:

- controllers resume without the original Executor;
- the unhealthy Machine is remediated by the declared mechanism;
- exactly one intended replacement is created;
- the replacement Node joins and becomes Ready;
- pending GitOps reconciliation resumes according to the selected profile; and
- current-generation Conditions converge back to `Ready=True`.

## Phase 5 — Evidence and cleanup

Record:

- outage duration and application probe continuity;
- Node/Machine/VM identity before, during, and after remediation;
- proof that no replacement occurred during the outage;
- proof that replacement occurred after management recovery;
- controller and Condition transition timestamps;
- GitOps behavior for the declared profile;
- residual-resource inventory; and
- terminal evidence location and checksum.

The scenario is FAIL if workload runtime depended unexpectedly on ok-mgmt, lifecycle
reconciliation continued from an undeclared controller, the desired state had to be
recreated from Executor-local state, duplicate infrastructure appeared, or recovery
required the original Executor.

## Evidence record

| Item | Value |
|---|---|
| Execution date | `PENDING` |
| Environment/profile | `PENDING` |
| Contract name/UID/generation | `PENDING` |
| Policy/correlation ID | `PENDING` |
| Outage start/end | `PENDING` |
| Application availability result | `PENDING` |
| GitOps profile/result | `PENDING` |
| Worker fault and MHC timeout | `PENDING` |
| Replacement Machine/VM/Node | `PENDING` |
| Final Conditions | `PENDING` |
| Raw evidence/checksum | `PENDING` |
| Verdict | `PENDING` |
| Reviewers | `PENDING` |
