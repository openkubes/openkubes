# Platform Source Identity Amendment — P-triple-prime

**Ticket:** OK-141

**Baseline:** `main` at `fbfa92c`

**Authoritative source:** `ok-observability` at
`b5f7be6a7ddab798f31f32197fcbb9e86a9798b6`

**Authorization:** `NO-GO`

**Infrastructure mutation:** none

**Failure injection:** none

## Purpose

The artifact-provenance checkpoint proved a package set that rendered the
Platform fixture identically, but also proved that those transitive wrapper
packages were absent from the Git revision bound by `P''`. The subsequent
`ok-observability` source amendment committed exactly those packages with a
machine-readable artifact lock and fail-closed verifier.

This additive amendment binds that new authoritative source identity. It does
not reinterpret or edit the historical `P''`, `R''`, or Phase-R-v3 fixture.

```text
P'''                    sha256:b0f25c63…17bd47bf
R'''                    sha256:636fe234…3128a16e
FixtureDigest'''        sha256:a2ae3437…a7f936f6
ok-observability source b5f7be6a…a9798b6
Authorization           NO-GO
```

Because the Platform source commit and closure are semantic inputs to `P`, the
new `P'''` changes the Cluster contract revision `R`. All projected lifecycle
and provider-prerequisite objects therefore carry `R'''`, and the exact
experiment receives a new `FixtureDigest'''`.

## Authoritative source closure

`minimal-observability-v4` binds:

- the exact `ok-observability` source commit;
- the artifact-lock path, schema, and Git-blob digest;
- exact membership and SHA-256 identity of the three wrapper packages;
- the unchanged chart, default values, alerting, dashboard, capability
  contract, and contract-test identities;
- the unchanged Provider Values, target reference, sync behavior, namespace,
  Pod Security, Secret contract, and capability-check semantics from `P''`.

The source amendment's own verifier proves that those wrapper packages contain
the pinned transitive Helm graph and render without dependency resolution.
The OpenKubes verifier independently proves that the bound files exist at the
new commit and match every declared digest.

## Boundary

```text
P'''
  desired Platform semantics
  authoritative Git source and package closure

NOT P'''
  Argo registration credentials
  AppProject or target RBAC bindings
  GitOps placement authority
  signer authenticity
  live convergence or capability evidence
```

Accordingly, the source gap is closed, while the existing M0b security,
compatibility, and runtime prerequisites remain blocking. No new OpenKubes
reconciler is required by this evidence.

## Result

```text
Platform source identity: complete offline
P''' / R''':             reproducible
FixtureDigest''':        reproducible
Historical v1-v3:        retained and reproducible
Tests:                   41 PASS
M0a / M0b:               NOT GRANTED
GO-1:                    NOT GRANTED
Infrastructure:          NO-GO
Failure Injection:       NO-GO
```

The next protocol amendment must bind `FixtureDigest'''` and produce a new
protocol digest. No historical T3 draft digest can authorize this fixture.
