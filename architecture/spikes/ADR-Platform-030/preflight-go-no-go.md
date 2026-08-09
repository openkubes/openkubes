# ADR-Platform-030 Outage Spike — Preflight GO/NO-GO

**Status:** Not evaluated
**Applies to:** `scenarios/management-plane-outage.md`
**Decision rule:** Every required gate must be verified. Any unchecked, failed,
ambiguous, expired, or unverifiable item results in `NO-GO`.

## Authorization boundary

> **GO authorizes only the exact failure injection recorded in this document. It does
> not authorize exploratory follow-up failures, broader targets, longer outage windows,
> force-finalization, credential changes, or additional mutations.**

An interesting or unexpected observation does not expand the test scope. Record it,
recover to baseline, and create a new scenario with a new Preflight review.

GO for this ADR-030 scenario proves only recoverability from a controlled outage with
preserved management state. It does not authorize or claim an ADR-031 disaster-recovery
test involving permanent etcd loss, shadow promotion, or orphan recovery.

## Test identity and immutable scope

| Field | Required value |
|---|---|
| Test ID | `PENDING` |
| Planned start/end | `PENDING` |
| Environment | `PENDING` |
| Workload cluster | `PENDING` |
| Contract name/UID/generation | `PENDING` |
| Target worker Machine/Node/VM/VMI | `PENDING` |
| Exact management-outage action | `PENDING` |
| Exact worker-failure action | `PENDING` |
| Maximum outage duration | `PENDING` |
| Expected MHC timeout/margin | `PENDING` |
| Recovery procedure/version | `PENDING` |
| Evidence destination | `PENDING` |

Changing any scoped field after GO invalidates the authorization and returns the test
to `NO-GO` until the complete Preflight is reviewed again.

## Gate A — Safety

- [ ] **Backup verified:** a current ok-mgmt backup exists outside the tested failure
      domain; identity, timestamp, generation/revision coverage, checksum, encryption,
      access, and retention are recorded.
- [ ] **Backup readable:** integrity verification completed successfully after backup
      creation; the test does not rely only on file existence.
- [ ] **Rollback tested:** the documented restart/rollback path with preserved
      management state has succeeded in a representative environment or prior approved
      rehearsal; operator, duration, and evidence are recorded.
- [ ] **Out-of-band management access verified:** the recovery operator can reach and
      control ok-mgmt VMs without using the ok-mgmt Kubernetes API.
- [ ] **Out-of-band infrastructure access verified:** ok-infra API, KubeVirt inventory,
      and recovery controls are reachable independently of ok-mgmt.
- [ ] **Fault boundary reviewed:** the exact commands and targets affect only the named
      ok-mgmt plane and one named workload worker; no wildcard, broad selector, or
      unresolved variable is used.
- [ ] **Workload failure budget verified:** the workload control plane, remaining
      workers, application replicas, disruption policy, and data integrity can tolerate
      the single declared worker failure.
- [ ] **Management-state preservation verified:** the management outage action does not
      intentionally delete etcd data, PVCs, VM disks, secrets, or cluster identity.
- [ ] **Recovery resources available:** required credentials, keys, tooling, personnel,
      and capacity are available for the full approved window plus recovery margin.

### Safety evidence

| Item | Evidence/link/checksum | Verified by | Time |
|---|---|---|---|
| Backup | `PENDING` | `PENDING` | `PENDING` |
| Backup integrity | `PENDING` | `PENDING` | `PENDING` |
| Rollback rehearsal | `PENDING` | `PENDING` | `PENDING` |
| Out-of-band access | `PENDING` | `PENDING` | `PENDING` |
| Fault-boundary review | `PENDING` | `PENDING` | `PENDING` |

## Gate B — Observability

- [ ] **Workload observer ready:** an independent observer can query workload API,
      Nodes, Pods, Services, DNS, and the continuous application probe while ok-mgmt is
      unavailable.
- [ ] **Infrastructure/provider observer ready:** an independent observer can query
      KubeVirt VM/VMI and provider inventory through ok-infra while ok-mgmt is
      unavailable.
- [ ] **Management observer behavior defined:** ok-mgmt Conditions are treated as
      unobservable during the outage, not inferred as current `False` values.
- [ ] **Baseline captured:** contract identity/generation, aggregate Conditions, CAPI
      objects, Machine/Node/VM mapping, MHC configuration, GitOps revision, workload
      health, and provider inventory are stored before GO.
- [ ] **Application probe independent:** the probe, its result store, and its alert path
      do not depend on ok-mgmt.
- [ ] **Evidence store independent:** raw evidence survives ok-mgmt outage and scenario
      cleanup.
- [ ] **Timestamps synchronized:** all observers use synchronized clocks; timezone,
      clock source, and maximum observed skew are recorded.
- [ ] **Evidence redaction verified:** collection excludes or redacts kubeconfigs,
      tokens, private keys, bearer credentials, and Secret values.

### Observability evidence

| Observer/artifact | Endpoint or location | Clock/skew | Verified by |
|---|---|---|---|
| Workload observer | `PENDING` | `PENDING` | `PENDING` |
| Infra/provider observer | `PENDING` | `PENDING` | `PENDING` |
| Application probe | `PENDING` | `PENDING` | `PENDING` |
| Baseline inventory | `PENDING` | `PENDING` | `PENDING` |
| Evidence store | `PENDING` | `PENDING` | `PENDING` |

## Gate C — Change Control

- [ ] **Parallel lifecycle changes frozen:** no create, scale, upgrade, delete,
      remediation experiment, provider upgrade, or policy change is active or scheduled
      for the test window.
- [ ] **Pending state reviewed:** queued GitOps revisions, paused resources, unhealthy
      Machines, deletion timestamps, finalizers, and outstanding operations are known
      and accepted.
- [ ] **Test window approved:** start, maximum duration, recovery margin, affected
      stakeholders, and communication channel are recorded.
- [ ] **Exact management failure defined:** command, target, expected effect, validation,
      and inverse/recovery action are reviewed.
- [ ] **Exact worker failure defined:** command, target, KubeVirt run-strategy behavior,
      expected Node state, validation, and inverse/recovery action are reviewed.
- [ ] **No immediate provider self-recovery:** the selected worker fault does not allow
      KubeVirt or another undeclared mechanism to recreate/restart the target before the
      CAPI remediation observation is meaningful.
- [ ] **Expected recovery path documented:** API/etcd validation, provider-version and
      credential checks, inventory comparison, reconciliation resume, and exactly-one
      replacement verification are ordered and assigned.
- [ ] **Cleanup defined:** failed test paths, residual VMs/Machines/Nodes, and evidence
      preservation have explicit cleanup procedures that do not strip finalizers by
      default.

### Change record

| Item | Approved value/reference |
|---|---|
| Change/test ticket | `PENDING` |
| Stakeholder notification | `PENDING` |
| Lifecycle freeze evidence | `PENDING` |
| Management failure procedure | `PENDING` |
| Worker failure procedure | `PENDING` |
| Recovery procedure | `PENDING` |
| Cleanup procedure | `PENDING` |

## Gate D — Authority

Roles may be held by the same person only if the approved operating policy permits it;
the assignment must still be explicit.

- [ ] **GO authority assigned:** the only role permitted to issue the final GO after
      reviewing every gate.
- [ ] **Failure-injection operator assigned:** permitted to execute only the exact
      recorded outage and worker-failure actions after GO.
- [ ] **Abort authority assigned:** may stop the scenario and order immediate recovery
      at any time; no additional approval is required to abort.
- [ ] **Recovery authority assigned:** owns management recovery and decides when
      reconciliation may resume within the approved procedure.
- [ ] **Observers assigned:** workload, infrastructure/provider, and evidence observers
      are named and confirm readiness.
- [ ] **Stop conditions agreed:** every operator and observer acknowledges the mandatory
      stop conditions below and the communication signal used to declare one.
- [ ] **No assumed authority:** loss of communication or ambiguity automatically means
      abort/recover, never implied permission to continue.

### Authority assignment

| Role | Person/identity | Contact/channel | Acknowledged at |
|---|---|---|---|
| GO authority | `PENDING` | `PENDING` | `PENDING` |
| Failure-injection operator | `PENDING` | `PENDING` | `PENDING` |
| Abort authority | `PENDING` | `PENDING` | `PENDING` |
| Recovery authority | `PENDING` | `PENDING` | `PENDING` |
| Workload observer | `PENDING` | `PENDING` | `PENDING` |
| Infra/provider observer | `PENDING` | `PENDING` | `PENDING` |
| Evidence observer | `PENDING` | `PENDING` | `PENDING` |

## Mandatory stop conditions

Any stop condition immediately ends fault injection and starts the approved recovery
procedure. Operators must not investigate by injecting another failure.

- unexpected workload control-plane degradation or loss of API quorum;
- an unexpected second worker or infrastructure component becomes unhealthy;
- application availability or data-integrity impact exceeds the declared budget;
- ok-infra, KubeVirt, storage, network, or provider instability outside the named fault;
- loss, corruption, or material delay of independent workload/provider observability;
- backup, rollback, credential, key, access, or recovery confidence changes;
- actual resource targeting or effects differ from the reviewed fault boundary;
- evidence contradicts a safety assumption or indicates an undeclared writer;
- duplicate Machine/VM creation, unintended deletion, or unexplained provider mutation;
- maximum outage duration or any phase-specific timeout is reached;
- recovery authority, abort authority, or required recovery personnel become
  unavailable; or
- the communication channel or timestamp integrity required for coordinated recovery
  is lost.

Additional environment-specific stop conditions:

| Condition | Detection signal | Immediate recovery action |
|---|---|---|
| `PENDING` | `PENDING` | `PENDING` |

## Binary gate evaluation

The GO authority completes this section immediately before execution.

| Gate | Result | Reviewer | Time | Notes |
|---|---|---|---|---|
| A — Safety | `NO-GO` | `PENDING` | `PENDING` | Default until every item is verified |
| B — Observability | `NO-GO` | `PENDING` | `PENDING` | Default until every item is verified |
| C — Change Control | `NO-GO` | `PENDING` | `PENDING` | Default until every item is verified |
| D — Authority | `NO-GO` | `PENDING` | `PENDING` | Default until every item is verified |

```text
overall = GO only if A == GO and B == GO and C == GO and D == GO
otherwise overall = NO-GO
```

**Overall decision:** `NO-GO`

**GO authority:** `PENDING`

**Decision timestamp:** `PENDING`

**Authorized Test ID and immutable-scope checksum:** `PENDING`

There is no conditional, partial, provisional, assumed, or verbal GO. Until this
document records all four gates as `GO`, an overall `GO`, the GO authority, timestamp,
and immutable-scope checksum, no failure-injection mutation is authorized.

## Execution handoff

After GO, execute only the phases in `scenarios/management-plane-outage.md`. On success
or abort:

1. recover ok-mgmt and the selected worker according to the approved path;
2. verify the baseline safety properties are restored;
3. preserve raw evidence before cleanup;
4. inventory all residual resources and pending reconciliation;
5. revoke any temporary access issued for the test;
6. record actual timings, deviations, and stop conditions; and
7. return this document to `Not evaluated` before any later test run. A prior GO is
   never reusable.
