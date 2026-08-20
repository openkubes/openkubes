# OK-141 Final Evidence Evaluation v1

Status: **Outcome A selected for the tested DEV profile**

Recorded: 2026-08-20

Baseline: `main` at `797d3cf`

## Decision question

Does the complete OK-141 evidence require a new durable OpenKubes-owned control
loop, or can the tested Cluster lifecycle be implemented with bounded execution,
deterministic evaluation and existing authoritative controllers?

## Scope of the result

The result is bound to the first tested DEV profile:

```text
connectivity       datacenter-isolated-v1
infrastructure     CAPI + CAPK + KubeVirt
enablement         CAAPH / Helm + Cilium
platform           centralized Argo CD on ok-shared
execution          bounded, receipt-driven Runner
readiness          bounded fail-closed evaluator
evidence           durable redacted receipts and independently verified digests
```

It is not a universal production-readiness, HA, scale, upgrade, disaster-recovery,
or public-API result.

## Bound execution evidence

| Block | Evidence | Result |
|---|---|---|
| Connectivity and CIDR authority | `datacenter-isolated-v1` declares fixed isolated CIDRs and requires no global allocator for this fixture | `PASS` |
| Happy Path | exact `R/E/P` create, controller convergence, bounded readiness and durable evidence | `PASS` |
| Negative controls | authorization denial, stale/conflicting evidence, wrong `R/E/P`, duplicate submission and process replacement | `PASS` |
| Enablement failure E1 | `NetworkReady=False` derived without OpenKubes repairing CAAPH, Helm or Cilium; exact restore returned the baseline | `PASS-FAIL-CLOSED-RESTORED` |
| Platform failure P1 | `PlatformReady=False` derived from Argo failure without OpenKubes repairing target resources; exact restore returned the baseline | `PASS-FAIL-CLOSED-RESTORED` |
| Delete D1-D7 | GitOps quiescence, Enablement removal, CAPI-owned deletion, provider/storage/credential cleanup and terminal absence proof | `PASS` |

The source checkpoints are bound by these public digests:

```text
CIDR/profile invariant:       sha256:72c2b258cdb116815f7a857c55c7927ee29150dca232119e766c08268acfa721
Happy-Path evaluation:        sha256:cadee90faf95e1d8882b5e9f6b865305c793d8ba8600566fe76466a9aca837f7
Negative-control closure:     sha256:3a36bbdc1245b9fd14468dc85c7bb00d11af0344428cca62be3d5ceef6a2557b
Mechanism-failure evaluation: sha256:3c89ef20bcdb518af29aa2c05498c937e348c7b12f106b102d49a76de6548f4d
Delete terminal closure:      sha256:9498323c20908b580fd127de7f25194491a56d6d47cbef4976cf05603b4f5ca8
Aggregate evaluation:         sha256:36d6f5d4dfd8ab926a5cf5a2e7a64c6319360366367d4f92c208abad4ff75ccf
```

## Closure of the former unresolved gaps

| Former gap | Final result for this profile | Ownership / mechanism |
|---|---|---|
| Allocation authority | `No new reconciler required` | isolated fixed-CIDR profile plus existing endpoint allocation |
| Enablement `E` / `NetworkReady` | `No new reconciler required` | deterministic E; CAAPH/Helm and Cilium converge; evaluator observes |
| Platform `P` / `PlatformReady` | `No new reconciler required` | deterministic P; Argo CD converges; evaluator observes |
| Aggregate Conditions | `No new reconciler required` | bounded evaluator satisfies every evidenced consumer |

Every `Unresolved` row in the Reconciler Necessity Test is therefore closed for
the tested profile by an existing controller, deterministic operation or bounded
read-only evaluator. No row reached `RequiresReconciler=Proven`.

## Final A/B/C/D classification

### A — selected

The bounded Runner submits authorized state and records receipts. CAPI/CAPK,
CAAPH/Helm, Cilium and Argo CD retain continuous convergence ownership. The
evaluator correlates current `R`, `E`, `P` and authoritative observations but does
not repair their resources.

The Happy Path, fail-closed negatives, controlled Enablement and Platform faults,
process replacement, idempotency and complete deletion all passed with that model.

### B — not selected

No evidenced consumer requires continuously published OpenKubes aggregate status.
CLI status/wait, operation completion and evidence verification are satisfied by
bounded evaluation and durable receipts. A concrete future Watch, policy or
automation contract may reopen this boundary.

### C — not supported

No OpenKubes-specific desired-state invariant was found that needs a new durable
corrective lifecycle loop. A broad OpenKubes Operator would add ownership without
an evidenced necessity.

### D — rejection boundary

An OpenKubes component that repairs CAPI, CAAPH/Helm, Cilium, Argo CD or their
owned resources would duplicate the proven authoritative owners and must be
rejected unless ownership is explicitly redesigned.

## Final verdict

```text
Overall OK-141 A/B/C/D:        A
RequiresReconciler:            No
Broad OpenKubes Operator:      Not justified
Persistent Status Adapter:     Not justified by current consumers
Bounded Runner/Evaluator:      Execution-proven for the tested DEV profile
Delete scenario:               PASS / terminally closed
Public OpenKubes API:          Not selected by this spike
ADR-030:                       Proposed; amendment required before acceptance
ADR-031:                       Separate authority/fencing and DR concern
```

## Management-outage boundary

The management-plane outage scenario remains unexecuted. It is not a blocker for
the A/B/C/D ownership classification because it cannot create a missing OpenKubes
reconciliation invariant: CAPI and the existing controllers remain the declared
owners before and after an outage.

It remains a blocker for stronger claims that:

- an existing workload runtime remains available while `ok-mgmt` is unavailable;
- reconciliation resumes correctly from persisted management state;
- exactly one replacement is produced after management recovery; or
- the selected DEV recovery procedure is operationally sufficient.

Those resilience claims require a separately authorized scenario and must not be
inferred from this result. Permanent state loss, authority and fencing remain in
ADR-031 scope.

## ADR-030 consequence

ADR-030 should remain `Proposed` while its broader acceptance matrix is incomplete.
Its next amendment should, however, reflect the evidence by:

1. making deterministic aggregate evaluation normative while treating durable
   status publication as optional until a forcing consumer exists;
2. replacing the mandatory OpenKubes Status Aggregator with a bounded evaluator or
   a future narrowly justified status adapter;
3. naming existing selected Enablement and GitOps controllers as convergence
   owners rather than implying OpenKubes-owned repair loops;
4. using current CAPI `ControlPlaneAvailable` source semantics while allowing an
   OpenKubes aggregate contract to expose a normalized name; and
5. retaining strict single-writer, revision-correlation, terminal-evidence and
   non-duplication invariants.

Scale, upgrade, management outage, broader recovery and migration evidence remain
future ADR acceptance work. They do not reopen outcome A unless they reveal a new
OpenKubes-specific invariant that satisfies the complete Reconciler Necessity Test.
