# ADR-Platform-034: `ok up` Convergence UX and Authorized Desired-State Transitions

**Date:** 2026-08-16
**Status:** Proposed

**Extends:** ADR-Platform-030
**Related:** ADR-Platform-004, ADR-Platform-007, ADR-Platform-011, ADR-Platform-013, ADR-Platform-017, ADR-Platform-023

---

## Context

OpenKubes needs a simple primary user path for creating and changing one Cluster
without exposing the implementation mechanics of CAPI, infrastructure providers,
bootstrap providers, GitOps, or a runner:

```text
openkubes.yaml + ok up
```

That simplicity must not turn `ok up` into an installation script, a generic
`kubectl apply` wrapper, or a second lifecycle source of truth. ADR-Platform-030
already establishes that Contracts describe desired state, Policies authorize
transitions, Executors submit them, and Controllers reconcile them. It does not
yet define the user-facing convergence command, local authoring discovery, or the
precise relationship between a requested revision, atomic acceptance, historical
transition outcome, and current health.

Without that precision, unsafe interpretations include deriving a new Scale
operation from temporarily lagging observed replicas, replaying a stale plan,
retrying an uncertain mutation with a consumed authorization, rolling authority
back after an execution failure, rewriting historical success after later drift,
or erasing deletion intent before cleanup is proven.

This ADR defines `ok up` as a convergence UX over the control-plane execution
model. It defines invariants and acceptance behavior, not a final public Cluster
API or a specific Authority Profile implementation.

## Decision drivers

- A one-command happy path without weakening lifecycle safety.
- Exactly one desired-state authority state at any point in time.
- Optimistic concurrency across users, automation, and recovery actors.
- Explicit, bounded, single-use authorization of semantic transitions.
- Durable correlation from authority acceptance to execution and evidence.
- Correct separation of desired authority, execution, convergence, and health.
- Provider-neutral and Authority-Profile-neutral semantics.
- Fail-closed behavior after stale plans, conflicts, and uncertain writes.
- An MVP scope small enough to test completely.

## Decision

### 1. Product scope: one directory, one Cluster Contract

For the initial `ok up` UX, one working directory represents exactly one
OpenKubes Cluster Contract:

```text
my-cluster/
└── openkubes.yaml
```

From that directory, the primary workflow is:

```bash
ok validate
ok plan
ok up
ok status
```

`ok down` requests controlled deletion through the same transition model.
Multi-Cluster bundles, environment transactions, and atomic coordination across
multiple Cluster Contracts are not implied by this directory model.

### 2. Authoring-file discovery

Without an explicit file argument, these commands look for exactly:

```text
./openkubes.yaml
```

They MUST NOT search parent directories or silently select another YAML file.
Absence of the default file is an error. An explicit file may be selected with:

```bash
ok up --file production.yaml
```

The short form `-f` MAY be provided as an exact alias. Explicit selection and
default discovery MUST otherwise have identical semantics.

The authoring file MUST NOT contain embedded provider credentials. Credentials
are supplied through references and bounded Authority Profile mechanisms.

### 3. Authoring form and canonical Contract

The discovered file is the user-facing authoring input. Before planning it is:

```text
parse -> default -> validate -> canonicalize -> requested revision
```

The canonical Contract, not YAML formatting, key order, comments, file timestamps,
or local paths, determines the requested semantic revision digest. Semantically
equivalent authoring inputs MUST produce the same revision.

This ADR reserves the filename and workflow but does not accept a final
`apiVersion`, `kind`, schema, default set, or provider vocabulary. Those require
separate versioned Contract decisions and executable compatibility tests.

If the authoring form differs from the canonical Contract, the canonical form is
a derived artifact. It MUST NOT become an independently editable competing source
of truth.

### 4. Command semantics

| Command | Meaning |
|---|---|
| `ok validate` | Parse, default, validate, and canonicalize without reading or mutating runtime authority. |
| `ok plan` | Compare authoritative desired revision with requested canonical revision and propose at most one semantic transition without mutation. |
| `ok up` | Recompute or verify the plan, obtain authorization, execute atomic acceptance, and observe the accepted revision. |
| `ok status` | Report authoritative revision, transition/execution correlation, current Conditions, and relevant durable evidence without mutation. |
| `ok down` | Propose and execute an authorized `DeleteCluster` transition; it is not direct provider-resource deletion. |

Machine-readable output, confirmation policy, non-interactive flags, and stable
exit codes require a separate CLI contract before implementation is declared
stable.

### 5. `ok up` proposes convergence; it is not a lifecycle operation

`ok up` is an umbrella convergence command. It does not itself name the semantic
lifecycle operation. The planner derives an operation from the previous
authoritative Contract and the requested canonical Contract:

```text
ABSENT -> R1             CreateCluster
Rn -> Rn+1               one classified semantic transition
Rn -> Rn                 NoOp
Rn -> DESIRED_ABSENT     DeleteCluster
```

Examples include `ScaleCluster`, `UpgradeCluster`, `ChangeNetworkProfile`, and
`ApplyPlatformProfile` as defined by their versioned transition contracts.

For the MVP, one plan MUST contain exactly zero or one semantic transition. If a
diff requires multiple transition classes, planning MUST fail and identify the
independent changes. Composite transitions require their own explicit contract,
authorization, ordering, failure, and evidence semantics.

### 6. Transition basis and observation

A new transition is derived from:

```text
previous authoritative desired revision -> requested canonical revision
```

It MUST NOT be derived from requested intent versus temporarily observed reality.
Observation determines convergence, completion, diagnosis, and recovery; it does
not select a new desired-state transition.

For example:

```text
authoritative desired replicas: 5
observed replicas:              3
requested replicas:            5
```

This produces no new `ScaleCluster` transition. The requested revision already is
authoritative but has not converged. `ok up` reports or resumes bounded observation,
or directs the user to controlled recovery. It does not submit another mutation.

### 7. Exact transition and authorization identity

Every proposed transition has a unique identifier and binds at least:

```text
transitionID
fromRevision
toRevision | DESIRED_ABSENT
operation
requestDigest
```

`transitionID` MUST be generated by a trusted, collision-resistant mechanism and
MUST be covered by the authorization. It is not a freely reusable user label.

Authorization covers the exact transition tuple, validity window, audience, and
permitted use count. The CLI proposes the transition; it does not authorize it.
The Executor independently verifies the protected decision and all point-of-use
preconditions before mutation.

After authorization, the immutable acceptance identity additionally binds the
`authorizationDigest`. Proposal identity therefore does not depend circularly on
an authorization that does not yet exist, while acceptance remains correlated to
the exact decision that permitted it.

### 8. Claim and atomic acceptance

Before the first possible external write, the Executor consumes the single-use
authorization through the durable claim semantics defined by the execution
profile. Claiming authorization and accepting desired authority are distinct
operations.

Authority acceptance MUST be one atomic compare-and-swap operation equivalent to:

```text
acceptTransition(
  expectedRevision,
  requestedRevision | DESIRED_ABSENT,
  transitionID,
  authorizationBinding
)
```

There MUST NOT be a separately observable `compare()` followed by an unconditional
`accept()`.

The operation returns one of these semantic results:

```text
ACCEPTED
PRECONDITION_FAILED
ALREADY_ACCEPTED
INDETERMINATE
```

- `ACCEPTED` means the expected predecessor matched and the requested state plus
  transition correlation became authoritative atomically.
- `PRECONDITION_FAILED` means the predecessor no longer matched; no mutation from
  this attempt occurred and re-planning is required.
- `ALREADY_ACCEPTED` means the complete immutable acceptance tuple is already
  durably present. Matching only the target revision is insufficient.
- `INDETERMINATE` means the caller cannot determine the result from the invocation
  response alone. The Authority Store itself MUST remain durably inspectable and
  unambiguous.

An accepted desired-state revision MUST be durably correlated with the transition
that established it. At minimum, the authoritative acceptance records:

```text
transitionID
fromRevision
toRevision | DESIRED_ABSENT
operation
authorizationDigest
acceptedAt
authorityProfile
```

`acceptedAt` and Authority Profile metadata are not part of the canonical Contract
revision identity.

### 9. Acceptance changes authority; convergence proves realization

Successful acceptance makes the requested revision authoritative immediately:

```text
accepted -> authoritative -> reconcile -> convergence evidence
```

It MUST NOT mean:

```text
accepted -> pending -> converged -> authoritative
```

At every point there is exactly one authoritative desired-state authority state:
`ABSENT`, one canonical revision, or `DESIRED_ABSENT`. Executor or controller
failure after acceptance does not implicitly restore the predecessor. Changing
away from an accepted state requires another explicitly authorized transition.

> **Acceptance determines authority. Transition evidence records realization.
> Current Conditions describe ongoing health.**

No execution failure or later health degradation implicitly rewrites an accepted
authority decision or a terminal historical transition outcome.

### 10. Deletion and desired absence

Deletion uses the same transition algebra but distinguishes intent from observed
absence:

```text
Rn
 |
 | DeleteCluster accepted
 v
DESIRED_ABSENT
 |
 | cleanup, finalizers, provider deletion, credential revocation
 v
CONFIRMED_ABSENT
```

`DESIRED_ABSENT` is authoritative immediately after acceptance.
`CONFIRMED_ABSENT` is a convergence result, not a desired revision.

The implementation MUST preserve deletion intent, transition correlation, cleanup
progress, and terminal evidence outside any object whose final deletion would erase
them. `UNMANAGED` or `NEVER_EXISTED` MUST NOT be confused with an accepted
`DESIRED_ABSENT` transition.

`ok down` MUST NOT strip finalizers, bypass Contract authority, or declare success
merely because the top-level object or Executor disappeared.

### 11. Orthogonal state spaces and writer ownership

Implementations expose five correlated but orthogonal state spaces:

1. **Desired Authority** — which desired revision is authoritative.
2. **Transition Decision** — which exact transition Policy allowed or rejected.
3. **Execution State** — what the Executor claimed, submitted, or could not
   determine.
4. **Transition Outcome** — whether that accepted revision was demonstrably
   realized for this transition.
5. **Current Health** — whether the currently authoritative state is now healthy
   and converged.

They MUST NOT be collapsed into one single-writer state machine. Ownership is:

| State | Owner |
|---|---|
| Authorization decision | Policy authority |
| Claim and submission evidence | Executor and durable execution ledger |
| Authoritative desired revision | Selected Authority Profile |
| Domain-specific observed status | Responsible controllers |
| Normalized aggregate Conditions | OpenKubes Status Aggregator |
| Historical proof | Durable Evidence Store |

A terminal Transition Outcome is immutable:

```text
PENDING -> RECONCILING -> SUCCEEDED
                       -> FAILED
                       -> RECOVERY_REQUIRED
```

Current Health remains dynamic:

```text
Ready <-> Reconciling <-> Drifted <-> Degraded
```

Thus a transition may remain historically `SUCCEEDED` while current health later
reports `Ready=False`. Later health changes append new status or evidence; they do
not rewrite the terminal outcome.

### 12. Crash, retry, and recovery semantics

Before acceptance, a stale plan or failed authorization causes no desired-state
mutation. After a single-use grant is claimed, uncertain mutation does not permit
automatic replay:

```text
CLAIMED -> uncertain result -> CLAIMED_INDETERMINATE_STOP
```

Recovery first inspects durable Authority and Evidence state by exact transition
identity:

```text
requested revision and exact tuple present  -> acceptance occurred
predecessor current and tuple absent         -> acceptance did not occur
different revision current and tuple absent  -> another transition won
```

Recovery may resume read-only observation when acceptance and submission are
durably proven. Any new or uncertain mutation requires an explicit recovery
decision and, when required by the operation contract, new authorization. Recovery
does not implicitly roll authority back.

### 13. Authority Profile conformance

OpenKubes may support API-backed and Git-backed desired-state authority. Their
mechanisms differ, but their semantics do not.

Every Authority Profile MUST document and produce evidence for:

1. its authoritative object, ref, or revision;
2. the representation of `expectedRevision`;
3. atomic compare-and-swap acceptance;
4. binding authorization to the accepted write;
5. atomic or inseparable persistence of transition correlation;
6. rejection of concurrent stale writers;
7. exact `ALREADY_ACCEPTED` recognition;
8. resolution of an indeterminate caller result;
9. durable representation of `DESIRED_ABSENT`; and
10. evidence proving those properties.

For an API-backed profile, optimistic concurrency may use a server-enforced
resource version or equivalent precondition. For a Git-backed profile, ordinary
`git pull`, local commit, and unconditional push are insufficient. The authoritative
ref update must be conditional on the expected predecessor and preserve the
authorized transition correlation.

### 14. User-visible `ok up` flow

```text
./openkubes.yaml
        |
        v
parse / default / validate / canonicalize
        |
        v
requested canonical revision
        +
current authoritative revision
        |
        v
derive zero or one semantic transition
        |
        v
plan -> policy authorization -> executor verification and claim
        |
        v
atomic CAS acceptance with durable correlation
        |
        v
new desired state immediately authoritative
        |
        v
CAPI / providers / Enablement / GitOps reconcile
        |
        v
Conditions + durable evidence
```

The mechanisms below the Contract remain replaceable. `ok up` does not gain direct
knowledge of provider-specific imperative workflows merely to make the top-level
command convenient.

## Consequences

### Positive

- Users receive a small and memorable primary workflow.
- Repeated convergence of an unchanged canonical request creates no new transition.
- Stale and concurrent writers fail closed at atomic acceptance.
- Authority, execution, historical outcome, and current health remain auditable.
- Provider and Authority Profile implementations remain replaceable.
- Executor crashes cannot silently roll back or redefine desired state.
- Deletion remains observable until cleanup is proven.

### Costs and trade-offs

- `ok up` requires authoritative desired state for planning and cannot be purely
  local rendering.
- Every Authority Profile must provide real concurrency and recovery evidence.
- A one-transition MVP may require independent changes to be applied in sequence.
- Durable ledgers, correlation, Conditions, and evidence add machinery beneath a
  deliberately simple command.
- Git-backed authority requires more than ordinary developer Git commands.

## Out of scope

This ADR does not decide:

- the final public `openkubes.yaml` schema, `apiVersion`, or `kind`;
- provider-specific fields, defaults, or provisioning implementations;
- whether API-backed or Git-backed authority is the default;
- exact CLI output schemas, prompts, exit codes, or shell completion;
- Multi-Cluster or environment bundles;
- composite transitions;
- automatic rollback policy;
- unrestricted shell, Helm, or `kubectl` escape hatches; or
- that the current CLI and runner already implement `ok up`.

## Acceptance criteria

This ADR may advance from `Proposed` only when executable Contract tests or
equivalent reviewed evidence demonstrate at least:

1. unchanged requested and authoritative revisions produce no new transition even
   while observed state is lagging;
2. a stale predecessor returns `PRECONDITION_FAILED` without mutation;
3. replay of the complete accepted tuple returns `ALREADY_ACCEPTED`;
4. the same target revision with a different tuple is a conflict;
5. exactly one of concurrent acceptance attempts wins;
6. a crash after acceptance leaves the accepted revision authoritative;
7. a lost acceptance response is resolved through durable identity inspection;
8. later health degradation does not rewrite a terminal `SUCCEEDED` outcome;
9. deletion remains `DESIRED_ABSENT` until cleanup and absence are proven;
10. a plan with multiple semantic transition classes is rejected;
11. authorization binds the exact predecessor, target, operation, and transition;
    and
12. at least one Authority Profile proves section 13 end to end.

## Current implementation status

The bounded Contract Executor work provides tested building blocks for
canonicalization, projection verification, authorization, single-use claims,
bounded submission, observation, and durable evidence. The public `ok up` workflow,
general transition classification, atomic desired-state acceptance, and stable
authoring schema are not thereby declared implemented.
