# ADR-Platform-030 Implementation Spike — Evidence Plan

**Status:** Planned
**Date:** 2026-08-09
**Decision under test:** ADR-Platform-030 (`Proposed`)

## Purpose

This spike tests the invariants in ADR-Platform-030. It does not select or build a
permanent OpenKubes controller merely to prove the architecture.

> **The spike succeeds when the architecture invariants are demonstrated under both
> successful reconciliation and controlled failure, not when a particular
> implementation has been completed.**

The first forcing profile is deliberately small:

```text
CLI / small Executor
        -> OpenKubesCluster contract instance
        -> policy decision
        -> CAPI/CAPK on ok-mgmt
        -> minimal Cluster Enablement
        -> declared GitOps profile
```

Reusing existing controllers, Jobs, scripts, and status adapters is preferred. A new
long-lived component is justified only by evidence that the required invariant cannot
be met with an existing reconciliation mechanism.

## Success oracle

An operation succeeds only when all profile-required Conditions are `True` for the
accepted contract generation. Executor exit status is never the success oracle.

```text
Contract generation N accepted
        -> policy authorized
        -> Executor submits desired state
        -> CAPI/CAPK reconciles
        -> Cluster Enablement reconciles
        -> GitOps reconciles the platform
        -> all required observedGeneration values equal N
        -> Ready=True
        -> durable evidence recorded
```

## Evidence requirements

Every scenario record must contain:

- environment and component versions;
- contract name, UID, generation, and immutable input revision;
- requester, policy decision, Executor identity, and correlation ID;
- timestamped source and aggregate Conditions including `reason`, `message`, and
  `observedGeneration`;
- relevant CAPI/CAPK, Enablement, and GitOps object UIDs;
- fault-injection start/end timestamps and exact commands used;
- workload availability probes and their raw results;
- terminal outcome and a link or checksum for raw logs;
- cleanup verification and residual-resource inventory; and
- reviewer sign-off.

Secrets, kubeconfigs, tokens, private keys, and bearer credentials must be redacted.
Evidence must be stored outside ephemeral Executor logs and outside any resource the
scenario deletes.

## Scenario matrix

| Scenario | Required proof | Status |
|---|---|---|
| Create success | Generation N reaches all required Conditions and `Ready=True` | Planned |
| Executor termination/restart | Accepted desired state continues reconciling; observation resumes without original process state | Planned |
| Stale generation | Prior `True` Conditions do not satisfy a newer generation | Planned |
| Authorization denied | Rejected before mutation; generation and downstream resources unchanged | Planned |
| Enablement failure | `NetworkReady`/`EnablementReady=False` with actionable Reason/Message; aggregate `Ready=False` | Planned |
| Platform failure | `PlatformReady=False`; infrastructure and Enablement ownership remain unaffected | Planned |
| Duplicate submission | Idempotent result; no duplicate cluster or provider resources | Planned |
| Delete | Finalizers, provider cleanup, credential cleanup, and externally retained terminal evidence | Planned |
| Break-glass | Separate authorization, bounded action, fencing, residual inventory, and audit record | Planned |
| Management-plane outage | Runtime/lifecycle failure-domain split and reconciliation resume | Planned; see `scenarios/management-plane-outage.md` |

## Guardrails

- Use a disposable test cluster and non-production application data.
- Do not combine the first test of a destructive fault with the only available backup.
- Establish an out-of-band path to the infrastructure plane before stopping ok-mgmt.
- Capture an independently stored, verified pre-test backup and document the rollback
  decision point.
- Pause unrelated lifecycle changes for the duration of fault-injection scenarios.
- Do not strip CAPI or provider finalizers as routine cleanup.
- Stop the scenario if the fault crosses its declared workload, infrastructure, secret,
  or network boundary.

## Acceptance package

The spike result consists of:

1. a completed scenario matrix;
2. raw, redacted evidence under `evidence/` or links to an immutable evidence store;
3. an explicit PASS/FAIL verdict for every ADR-030 acceptance condition;
4. deviations between the proposed model and observed controller behavior;
5. the smallest justified target implementation; and
6. a recommendation to accept, revise, or reject ADR-030.

Incomplete or happy-path-only evidence cannot produce an `Accepted` recommendation.
