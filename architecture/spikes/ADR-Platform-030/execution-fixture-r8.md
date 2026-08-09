# R8 Exact Disposable Execution Fixture

> **Historical checkpoint:** `phase-r-v1` and FixtureDigest `a97e1e31...df82c9ba`
> remain valid and byte-for-byte verifiable, but are superseded for GO-1 preparation
> by the Phase-R cluster-semantics amendment. They do not bind worker count, complete
> OS/machine/provider semantics, or the exact management/infra projection. See
> `phase-r-cluster-semantics-amendment.md`.

Status: **Offline closure candidate complete; review pending**

Recorded: 2026-08-09

## Result

R8 assembles the already evaluated Phase-R mechanisms into one reproducible test
specification. It introduces no new controller, public API, renderer, infrastructure
write path, or GO authorization.

The authoritative checked-in candidate is
`harness/fixtures/execution/phase-r-v1.json`:

```text
R              sha256:a880b119148dbd6e2532932a91b1367d04b042f7a638f891da02b9a1bf9199c7
E              sha256:7393fdbfd31a6e8122860f4b458540672083e2323f5d1a47a776ff39db836568
P              sha256:17ef42f4187a743fa09f6d955e70811af47763c4f98a4e73735da70055bc8969
FixtureDigest  sha256:a97e1e31e1f09cc44210679b48130e36edd90709d84ba3ee7b729ba5df82c9ba
Authorization  NO-GO
```

`FixtureDigest` is the digest of the canonical fixture without its self-declared
`fixtureDigest` field. It is intentionally different from `R`: `R` identifies desired
Cluster semantics, while `FixtureDigest` additionally identifies test methodology,
tools, expected evidence, assertions, and negative controls.

## Identity graph

```text
stable Contract identity (default/disposable-ok141)
  -> E: Enablement semantics
  -> P: Platform semantics

R
  -> desired Cluster semantics, including E and P

FixtureDigest
  -> R + E + P
  -> connectivity and allocation policy
  -> canonicalizer/evaluator/evidence identities
  -> expected evidence and assertions
  -> exact negative-control set
```

The profiles do not embed `R`. Embedding it would make the definitions circular,
because `R` already contains the desired `E` and `P`. The execution fixture is the
correlation authority for this experiment.

## Bound inputs

The fixture binds:

- the raw Contract artifact, Contract schema, canonicalization profile, and `R`;
- `datacenter-isolated-v1`, fixed disposable Pod/Service CIDRs, forbidden ranges,
  and the allocation boundary;
- Cilium 1.19.6, immutable chart/values/render/image identities, and `E`;
- `minimal-observability-v1`, exact Application membership, exact Git commit, and
  `P`;
- the required-condition profile and fail-closed freshness rules;
- the evaluator, harness, and evidence-schema identities;
- five positive assertions and eight named negative controls; and
- expected evidence from CAPI, KubeVirt, the workload Cluster, Enablement, GitOps,
  aggregation, and the final evidence bundle.

The Cilium and Argo mechanisms remain **configurable, not execution-proven**.

## Negative controls

The exact set is:

```text
NC-R-WRONG
NC-E-WRONG
NC-P-WRONG
NC-STALE-GENERATION
NC-MISSING-SOURCE
NC-CONFLICTING-AUTHORITY
NC-HISTORICAL-SUCCESS
NC-TAMPERED-EVIDENCE
```

No negative control may produce `Ready=True`. Evidence tampering must stop before a
readiness result is accepted.

## Offline verification

`verify-fixture` independently reconstructs the semantic identities from the bound
source files and fails closed for digest, membership, target, tool, profile, or
negative-control mismatches. The test suite also injects altered `R`, `E`, `P`, tool
identity, connectivity, and negative-control membership.

The current suite passes 11 tests. This proves reproducibility of the offline test
specification only. It does not prove controller convergence or runtime readiness.

## Phase boundary

R8 closes the implementation portion of Phase R. Review and merge of the complete
read-only bundle are still required before Phase R becomes the baseline for a later
GO request.

No `GO-1` artifact is prepared here. A future GO must authorize this exact
`FixtureDigest` and is initially limited to create, converge, and observe. Drift,
restart, deletion, management outage, break-glass, and failure injection remain
outside that scope and remain **NO-GO**.
