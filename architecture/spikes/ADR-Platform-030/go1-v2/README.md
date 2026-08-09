# OK-141 T3 — GO-1 Protocol v2

Status: **structurally complete; BLOCKED; GO-1 NOT GRANTED**

Baseline: `main @ 1d74060961b2775740e68ecbe30e576f8fa34dea`

Bound fixture:
`sha256:67fa2e63bba98d8cc70f680e8df56dea5803c0a0d8c5db81ab78578daacebd9f`

## Purpose

T3 formulates the complete protocol shape for exactly one future
`create + converge + observe` experiment. It does not satisfy prerequisites,
enable a phase, authorize a mutation, install a controller, create credentials,
or grant GO-1.

```text
protocol structurally complete
!= prerequisites satisfied
!= ready for GO decision
!= GO-1 granted
```

The historical uncommitted v1 draft remains isolated on
`spike/OK-141-go1-protocol`. T3 neither copies its obsolete identities nor
changes that worktree.

## Closed technical determinants

Phase-R-v3 now fixes what the v1 draft could not:

- one control plane and one worker;
- exact Contract, `R''`, `E'`, `P''`, and `FixtureDigest''`;
- three exact provider prerequisites targeting only `ok-infra`;
- eight exact CAPI lifecycle objects targeting only `ok-mgmt`; and
- exact projection, authority-map, Application-set, Provider-Values, and
  condition-profile identities.

The protocol exposes the semantic operation `ApplyReviewedObjectSet`, not a
generic shell endpoint. Both prospective submission groups and all six phases
remain disabled.

## Blocking prerequisites

T3 records fourteen fail-closed blockers in five domains:

```text
Executor/security
  executor artifact identity
  short-lived least-privilege submission credentials

M0a / CAAPH
  installation/RBAC/retry proof
  immutable Cilium chart resolution
  current R/E/Fixture-bound submission object

M0b / GitOps
  placement and recovery authority
  secure immutable target registration
  exact AppProject/workload RBAC
  target StorageClass and credential lifecycle
  retention and alert-delivery acceptance boundary

Operations
  independent observers and human authorities
  independent evidence destination
  verified recovery evidence and out-of-band access
```

`M0a` and `M0b` are not granted by this document. Their closure changes the
protocol and therefore requires a new canonical/raw digest and review.

## Digest and authorization

`go1-protocol-v2.sha256` identifies the exact raw T3 draft. It is informational
only. A later GO decision must bind a newly finalized protocol digest and the
unchanged Phase-R-v3 FixtureDigest separately.

```text
DraftDigest present       != GO
Protocol merged           != GO
All prerequisites proven  != GO
Explicit human grant      == only possible GO transition
```

## Verification

```bash
python3 architecture/spikes/ADR-Platform-030/go1-v2/verify_go1_protocol_v2.py \
  --protocol architecture/spikes/ADR-Platform-030/go1-v2/go1-protocol-v2.yaml \
  --digest-file architecture/spikes/ADR-Platform-030/go1-v2/go1-protocol-v2.sha256

python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/go1-v2/tests \
  -p 'test_*.py' -v
```

## State

```text
T3:                 structurally complete / BLOCKED
M0a / M0b:          NOT GRANTED
Ready for GO review: no
GO-1:               NOT GRANTED
Infrastructure:     NO-GO
Failure Injection:  NO-GO
```
