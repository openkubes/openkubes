# OK-141 T3 Binding Amendment — GO-1 Protocol v3

Status: **structurally complete; BLOCKED; GO-1 NOT GRANTED**

Baseline: `main @ d10c871b17af7b998ad3b6705bb2f6c7073aa632`

Bound fixture:
`sha256:a2ae3437645db5a83426b89d36d00693d2600e4ef20dc1aba2650dcda7f936f6`

## Purpose

This additive T3 amendment binds the complete protocol shape for exactly one future
`create + converge + observe` experiment. It does not satisfy prerequisites,
enable a phase, authorize a mutation, install a controller, create credentials,
or grant GO-1.

```text
protocol structurally complete
!= prerequisites satisfied
!= ready for GO decision
!= GO-1 granted
```

The historical v1 draft and merged v2 protocol remain unchanged evidence. This
amendment creates a new protocol identity rather than reinterpreting either
historical draft.

## Closed technical determinants

Phase-R-v4 fixes the authoritative Platform source identity while retaining the
same intended render. The protocol now binds:

- one control plane and one worker;
- exact Contract, `R'''`, `E'`, `P'''`, and `FixtureDigest'''`;
- three exact provider prerequisites targeting only `ok-infra`;
- eight exact CAPI lifecycle objects targeting only `ok-mgmt`; and
- exact projection, authority-map, Application-set, Provider-Values,
  condition-profile, `ok-observability` source-commit, and package-lock
  identities.

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

`go1-protocol-v3.sha256` identifies the exact raw T3 amendment draft. It is informational
only. A later GO decision must bind a newly finalized protocol digest and the
Phase-R-v4 FixtureDigest separately.

```text
DraftDigest present       != GO
Protocol merged           != GO
All prerequisites proven  != GO
Explicit human grant      == only possible GO transition
```

## Verification

```bash
python3 architecture/spikes/ADR-Platform-030/go1-v3/verify_go1_protocol_v3.py \
  --protocol architecture/spikes/ADR-Platform-030/go1-v3/go1-protocol-v3.yaml \
  --digest-file architecture/spikes/ADR-Platform-030/go1-v3/go1-protocol-v3.sha256

python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/go1-v3/tests \
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
