# OK-141 Read-only Closure Plan

Status: **Phase-R closure candidate complete; review pending**

Recorded: 2026-08-09

Branch: `spike/OK-141-read-only-closure`

Baseline: `main` at `c4e3657`

## Purpose

Close every remaining OK-141 question that does not require infrastructure mutation,
then produce one exact disposable execution fixture for later checksum-bound GO gates.

This phase does not authorize:

- applying resources to a Kubernetes API;
- installing an Enablement or GitOps controller;
- creating, changing, or deleting a Cluster;
- failure injection;
- changing ADR-030 or ADR-031;
- selecting a public OpenKubes API; or
- treating rendered manifests as execution proof.

Infrastructure mutation and failure injection remain **NO-GO**.

## Phase boundary

```text
Phase R — read-only closure
  -> contracts, fixtures, deterministic tooling, render/diff, evidence schema
  -> produces an immutable execution fixture
  -> no infrastructure writes

Phase M — mutation-gated execution
  -> uses only the reviewed execution fixture
  -> requires a new, checksum-bound GO per bounded fault scope
  -> produces runtime evidence, not new design scope
```

GO for one Phase-M stage never authorizes another stage.

## Work packages

| ID | Work package | Mutation required? | Current state | Exit evidence |
|---|---|---:|---|---|
| R1 | CIDR/connectivity profile invariant | No | **Closed for first fixture** | `datacenter-isolated-v1` defines address scope, validation, and authority boundary |
| R2 | Canonicalization harness | No | **Implemented; review pending** | Versioned schema/defaults/non-semantic-field rules, canonical JSON, raw and normalized digests |
| R3 | Bounded evaluator | No | **Implemented; review pending** | Deterministic `True`/`False`/`Unknown` results over retained fixtures |
| R4 | Evidence manifest and verifier | No | **Implemented; review pending** | Content-addressed manifest, tool identities, independent verification |
| R5 | Positive and negative fixtures | No | **Implemented; review pending** | Current success plus stale/wrong/missing/conflicting/tampered controls |
| R6 | Rendered Enablement candidate | No for preparation | **Offline candidate defined; review pending** | Immutable E, candidate resources, RBAC/ordering/retry expectations, no apply |
| R7 | Rendered Platform/GitOps candidate | No for preparation | **Offline candidate defined; review pending** | Immutable P, deterministic root/member set, target identity, no apply |
| R8 | Exact disposable execution contract | No | **Implemented; review pending** | One checksummed bundle containing R/E/P, policy, sources, probes, controls, and expected evidence |

R6 and R7 can prove only feasibility and exact test input. Convergence, retry, drift
correction, and readiness against real controllers remain Phase-M claims.

## Phase-R output

Phase R completes only when one reviewed bundle fixes:

```text
canonicalization profile and tool digest
raw contract digest
normalized intent revision R
connectivity/allocation policy
desired Enablement revision E
desired Platform revision P
required-condition profile
authoritative source identities and freshness rules
positive and negative controls
rendered candidate resources and their hashes
expected evidence manifest
independent verification procedure
```

The bundle is a test contract, not an accepted product API. Its checksum becomes an
input to each later GO decision.

The Phase-R closure candidate is:

```text
R              sha256:a880b119148dbd6e2532932a91b1367d04b042f7a638f891da02b9a1bf9199c7
E              sha256:7393fdbfd31a6e8122860f4b458540672083e2323f5d1a47a776ff39db836568
P              sha256:17ef42f4187a743fa09f6d955e70811af47763c4f98a4e73735da70055bc8969
FixtureDigest  sha256:a97e1e31e1f09cc44210679b48130e36edd90709d84ba3ee7b729ba5df82c9ba
Authorization  NO-GO
```

`R` includes the desired `E` and `P`, while the Enablement and Platform profiles bind
to the stable Contract identity (`namespace/name`). The fixture provides the explicit
`R -> E` and `R -> P` correlation. This avoids a circular digest definition in which
`R` contains `E/P` while `E/P` also contain `R`.

## Phase-M staging

The future execution proof is split into separately authorized scopes:

| Gate | Authorized scope | Explicitly not authorized |
|---|---|---|
| GO-1 | Create disposable Cluster and observe baseline CAPI, E, P, and aggregate convergence | Drift, restart, deletion, management outage |
| GO-2 | Reviewed bounded restart/retry/drift controls | Deletion and management outage |
| GO-3 | Deletion, finalizer/cleanup, and terminal evidence | Management outage |
| GO-4 | Management-plane outage plus the exact reviewed worker-failure scenario | Any exploratory second failure |

Every gate must use the preflight protocol, name stop conditions and authorities, bind
the exact fixture/fault scope by checksum, and return to `NO-GO` after completion or
scope change.

## Classification discipline

- Render success is not reconciliation success.
- Fixture success is not live-controller success.
- Existing-controller feasibility is not an accepted implementation profile.
- A missing capability does not imply a missing controller.
- A persistent authority or evidence store is not automatically a Cluster lifecycle
  reconciler.
- New runtime observations may change the A/B/C/D result; Phase R must not preselect
  that result.

Current checkpoint:

```text
Overall OK-141:            unclassified
Leading hypothesis:        A
RequiresReconciler:        none proven
Broad Operator:            not justified
Persistent Status Adapter: not justified
Infrastructure:            NO-GO
Failure Injection:         NO-GO
```
