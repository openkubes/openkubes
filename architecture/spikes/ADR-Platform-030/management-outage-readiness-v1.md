# OK-141 Management-Outage Readiness Assessment v1

Status: **BLOCKED / NO-GO / read-only assessment**

Recorded: 2026-08-20

Baseline: `main` at `b252fe5`

## Purpose

This assessment evaluates whether the final OK-141 management-plane outage and
reconciliation-resume scenario can run after the successful D1-D7 deletion. It
does not authorize Cluster creation, backup creation, an outage, worker failure,
recovery action or other infrastructure mutation.

## Current state

```text
Outcome A classification:             complete
ADR-030 evidence amendment:           complete / Proposed
Prior disposable environment:         terminally absent
Management-outage scenario:           not executed
Outage preflight overall decision:     NO-GO
```

D7 proved that all 39 identities bound across `ok-shared`, `ok-mgmt` and
`ok-infra` were absent. There is therefore no workload target, worker, application
probe, MachineHealthCheck baseline or runtime identity graph on which the outage
scenario can execute.

## Binary gate assessment

### Gate A — Safety: BLOCKED

- No current ok-mgmt backup outside the tested ok-mgmt/ok-infra failure domain is
  bound and integrity-verified for this scenario.
- The restart/recovery path with preserved management state has not been proven by
  a representative rehearsal.
- The accepted DEV profile permits total state loss and rebuild instead of restore,
  but `rebuildPathProven=false` and `lifecycleContinuityClaimAllowed=false` remain
  explicit. That risk acceptance cannot prove an ADR-030 preserved-state recovery
  scenario.
- Out-of-band ok-infra access is plausible and previously exercised, but the exact
  management-plane VM identity, outage action and inverse action are not currently
  bound to a test window.

### Gate B — Observability: BLOCKED

- The disposable workload Cluster and its kubeconfig no longer exist.
- No independent continuous application probe or current workload observer exists.
- No pre-outage CAPI/Machine/Node/VM identity baseline can be captured until a new
  forcing Cluster has converged.
- The existing independent evidence-publication mechanism is suitable in principle,
  but a new scenario-specific evidence destination and observer binding are required.

### Gate C — Change Control: BLOCKED

- No target worker Machine/Node/VM/VMI exists.
- No MachineHealthCheck or equivalent replacement mechanism is bound and baselined.
- The prior one-control-plane/one-worker Happy-Run fixture cannot demonstrate one
  worker failure while retaining an application availability budget.
- Exact management-outage, worker-fault, recovery and residual-cleanup operations are
  not yet rendered or reviewed.

### Gate D — Authority: BLOCKED

- GO, failure-injection, abort, recovery and observer assignments must be rebound to
  one exact future window and immutable scenario digest.
- A prior grant, general trust statement or completed Happy-Run authorization cannot
  authorize this separate critical outage scenario.

## Minimum executable forcing fixture

The smallest defensible DEV fixture is:

```text
workload control plane:     1 (intentional DEV solo model; no HA claim)
workers:                    at least 2
test application:           at least 2 replicas with worker anti-affinity
remediation:                one exact MachineHealthCheck profile
GitOps:                     centralized Argo CD on ok-shared
observer/evidence:          independent of ok-mgmt
```

This does not introduce HA for ok-mgmt or the workload control plane. The second
worker exists only to make the declared single-worker failure budget meaningful.

## Minimal closure sequence

1. **Recreate a new disposable fixture** through the already proven bounded Runner,
   with at least two workers and a new immutable `R/E/P/FixtureDigest` chain.
2. **Install and prove the forcing probe and MachineHealthCheck** while ok-mgmt is
   healthy.
3. **Create and independently verify a current ok-mgmt backup** outside both tested
   failure domains, or explicitly change the Jira/ADR scenario so it no longer claims
   preserved-state recovery.
4. **Rehearse the recovery procedure** on a representative disposable management
   target and retain evidence of the restart path and duration.
5. **Bind exact identities and operations** for the ok-mgmt outage, one workload
   worker fault, recovery, exactly-one replacement observation and cleanup.
6. **Evaluate all four binary gates** and issue a new short-lived checksum-bound GO.
7. **Execute outage, worker fault, recovery and closure** with independent observers.

## Decision boundary

Two legitimate project choices remain:

### Execute inside OK-141

Keep OK-141 `In Progress`, satisfy the backup/rehearsal and new-fixture gates, then
run the critical scenario. This completes the issue exactly as currently written.

### Move resilience evidence to a dedicated follow-up

Retain outcome A and the completed component-discovery spike, create a separate issue
for management-outage/recovery conformance, and amend OK-141 acceptance scope before
closing it. This is a governance decision; this assessment does not make it.

## Current verdict

```text
Architecture classification A:       PASS
Component-necessity question:         CLOSED
Management-outage readiness:          BLOCKED
Infrastructure mutation:              NO-GO
Outage / worker failure:               NO-GO
OK-141 Jira completion:                BLOCKED by current acceptance text
```
