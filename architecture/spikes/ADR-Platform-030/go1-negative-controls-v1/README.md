# OK-141 Non-destructive Negative Controls v1

Status: **Non-destructive negative-control block complete**

Recorded: 2026-08-20

This checkpoint prepares the first post-Happy-Run negative-control block. It is
strictly limited to fail-closed evaluation, terminal receipt replay, and read-only
before/after observations. It does not authorize Cilium or Argo faults, deletion,
outage, rollback, cleanup, or any lifecycle mutation.

## Result so far

The current `ok-cluster` runner at commit
`432bc2b2361fc4e8b56c368292c5df7fca504f57` passed 15 targeted tests covering:

- rejected or mismatched authorization;
- stale and conflicting evidence;
- wrong revision and target correlation;
- immutable, idempotent receipts;
- exact duplicate launch behavior; and
- process replacement and resume from durable receipts.

A newly built runner binary then consumed the complete twelve-stage Happy-Run
receipt prefix and returned:

```text
state:                 COMPLETED
completedStages:       12
requiresAuthorization: false
mutationAllowed:       false
```

No credential, endpoint, Kubernetes client, or cluster contact was available to
that command. This is direct execution evidence that process replacement cannot
turn a terminal successful plan into a new mutation.

The bounded live no-write closure then passed with EvidenceDigest
`sha256:55d435b49626d9d65e8be720af5f314c540011bfa2033e6f87e9647d8a1bcb01`:

- all eleven projected object UID/generation/spec identity hashes were identical
  before and after the local negative operations;
- wrong `R` was rejected;
- terminal replay remained `COMPLETED` with `mutationAllowed=false`;
- both Nodes remained Ready;
- Cilium remained 2/2 and its operator available; and
- the `local-path` StorageClass remained present.

The private raw API responses were never retained. The published closure contains
only hashes, counts, booleans, and normalized result categories.

## Five controls

| Control | Current proof | Live action still required |
|---|---|---|
| Authorization denied | signed/typed authorization mismatch paths fail before claim or mutation; wrong bound identity was rejected locally between equal live snapshots | complete |
| Stale generation/evidence | stale generation, foreign Cluster UID, wrong E, missing source, and conflicting authority all fail closed | complete |
| Duplicate submission/idempotency | exact duplicates are idempotent; the completed twelve-receipt prefix returned terminal `COMPLETED` with mutation disabled between equal live snapshots | complete |
| Executor restart/resume | fresh process reconstructed all twelve stages from immutable receipts | complete |
| Wrong R/E/P correlation | wrong plan/profile/evidence identities are rejected before source contact or readiness acceptance | complete |

The completed live closure required no Kubernetes write. It recorded a bounded
before snapshot of the eleven projected objects, performs the local rejected
authorization and terminal replay, then records the same bounded after snapshot.
The snapshot retains only hashes of UID, generation, spec, and exact RBAC content;
raw objects, UIDs, resourceVersions, endpoints, and credentials remain private.

## Acceptance

The block passes only when:

1. every offline control is `PASS`;
2. the fresh-process resume decision is terminal `COMPLETED` and
   `mutationAllowed=false`;
3. the rejected authorization performs no cluster contact;
4. before and after projected-object snapshot digests are equal; and
5. the disposable Cluster remains healthy after the no-write block.

Any unexpected write, changed projected spec/generation, credential exposure,
ambiguous receipt, or non-terminal replay is a stop condition.

All five acceptance conditions passed.

## Explicit exclusions

- no Enablement or Platform fault;
- no retry of a mutating stage;
- no create, update, patch, apply, replace, or delete;
- no Secret content read;
- no Pod exec or log read;
- no Force Delete or finalizer change;
- no cleanup;
- no management-plane outage; and
- no failure injection.
