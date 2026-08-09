# R7 Platform Offline Candidate

Status: **Offline candidate defined; GitOps convergence unproven**

Recorded: 2026-08-09

## Candidate

The minimal Platform fixture contains exactly one existing capability-owned leaf:
`ok-observability-standard`.

```text
profile                    minimal-observability-v1
source repository          https://github.com/openkubes/ok-observability.git
source commit              fe394da8875adecc3b497137e546cecabd710d1d
source path                profiles/ok-observability-standard
target registration        disposable-ok141
target namespace           observability
required Applications      1
semantic P                 17ef42f4187a743fa09f6d955e70811af47763c4f98a4e73735da70055bc8969
Application-set digest     60f95393486bdb2276d4e7af1aadc57e17eb722b340e1bc0351295f3f5e53c18
```

The leaf retains the immutable source commit plus SHA-256 identities for its capability
contract, Contract Test, profile chart, and default values.

`P` binds to the stable target Contract identity rather than embedding `R`. R8 supplies
the explicit `R -> P` correlation and therefore avoids a circular digest definition.

Applications such as OpenWebUI/OpenClaw are not members of this Platform profile.

## Renderer and authority boundary

The committed Application is test input, not output from a new OpenKubes renderer. The
harness only compares it with the independently declared Platform profile:

```text
Platform profile P
  -> exact required Application membership
  -> exact repository/path/commit
  -> exact target registration/namespace
  -> required capability checks

candidate Application input
  -> inspected, never generated or applied by the harness
```

The eventual authoritative interpretation and convergence belong to the selected Argo
CD control plane. No OpenKubes GitOps instance, App-of-Apps root, target registration,
credentials, or Application is created by R7.

## Offline negative controls

Automated tests prove:

- a branch such as `main` cannot serve as accepted immutable `targetRevision`;
- a missing required Application fails membership validation;
- a changed capability-leaf commit changes P;
- the same Application targeting a foreign Cluster registration fails closed;
- extra/missing membership cannot pass; and
- absent capability checks are rejected.

## Known offline limits

- The target registration name is not immutable runtime identity. Phase M must
  correlate the Argo registration Secret/cluster identity with the exact disposable
  CAPI Cluster UID and R.
- The candidate source may require dependency/materialization and provider values
  before Argo can render it. R8 pins the source commit and known source-artifact
  identities; exact runtime materialization remains a Phase-M precondition and must
  fail closed if the selected GitOps mechanism cannot reproduce it.
- `Synced`, `Healthy`, applied commit, self-heal, capability checks, and observer-loss
  behavior require a real selected GitOps controller and target Cluster.
- Placement on `ok-shared` remains a recommendation with its own NO-GO feasibility
  gates, not installation authorization.

## R7 boundary

```text
P construction:              deterministic / offline proven
Required membership:         exact / offline proven
Immutable Git source:        exact commit
Target intent binding:       fixture-defined
Runtime target UID binding:  pending Phase M
GitOps convergence:          configurable / not proven
PlatformReady:               fixture-defined / live proof pending
RequiresReconciler:          none proven
Infrastructure:              NO-GO
```
