# Platform Fixture Amendment — P-double-prime

**Ticket:** OK-141

**Baseline:** `main` at `30e9442`

**Authorization:** `NO-GO`

**Infrastructure mutation:** none

**Failure injection:** none

## Purpose

T2b proved Argo CD configurable for Platform convergence and also proved that
the Phase-R-v2 Platform identity was semantically incomplete. This additive
amendment closes only those Platform-fixture gaps. It does not install Argo,
register a Cluster, grant M0b, prepare T3, or authorize GO-1.

```text
P'                         historical; reproducible; insufficient for GO-1
P''                        sha256:0dcfbe10…a650439b
R''                        sha256:62e4d20f…437d9f78
FixtureDigest''            sha256:67fa2e63…aacebd9f
Authorization              NO-GO
```

Because the Cluster contract carries the Platform revision, changing `P'` to
`P''` also changes the semantic Cluster intent `R`. New projections therefore
carry `R''`; the v1/v2 contracts, projections, tools, and fixtures remain
unmodified historical evidence.

## P-double-prime membership

`minimal-observability-v3` binds:

- exact membership of three direct Argo Applications: the composed Helm chart,
  Prometheus rules, and the required dashboard ConfigMap;
- the exact source commit and source artifact digests;
- normalized cluster-specific Provider Values and their semantic digest;
- the `ok-observability` namespace and privileged Pod Security labels required
  by the host-access workloads in this profile;
- automated sync, prune, self-heal, non-empty, retry/backoff, namespace
  creation, and pruning semantics;
- an immutable target-identity reference with scheme `capi-cluster-uid/v1`;
- the exact capability contract/test identities and bounded parameters; and
- the required Secret name and keys, but never their values.

The alert acceptance parameter is deliberately `firing-only`. The selected
fixture does not bind an external alert-receiver endpoint, so delivery is not
claimed by this offline amendment.

The pinned `ok-observability` source also documents OpenSearch log retention/
ILM as not implemented. `P''` must not turn that source limitation into a false
claim. Before M0b can claim the complete capability contract, it must either
bind a reviewed retention implementation or explicitly narrow the disposable
test's accepted capability scope. M0b must additionally prove that the bound
`local-path` StorageClass exists and that the referenced credentials Secret is
available without retaining secret values as evidence.

## Security and mechanism boundary

```text
P''
  desired Platform membership and behavior
  immutable target identity reference

NOT P''
  Argo registration Secret or credentials
  AppProject policy and workload RBAC
  GitOps control-plane placement authority
  credential rotation, revocation, backup, or recovery
```

Those excluded items remain blocking M0b mechanism/security prerequisites.
The registration name is only an address. A later bounded evaluator must
resolve the target reference against the current CAPI Cluster UID and compare
it with independent workload and registration evidence.

## Offline proof

The verifier fails closed for:

- changed Provider Values under the old digest;
- missing or additional required Applications;
- changed namespace or Pod Security semantics;
- changed target identity references;
- mutable or unresolved Git source revisions; and
- any mismatch between the exact Application documents and their bound
  semantic digests.

The new Phase-R-v3 fixture additionally verifies `R''`, all projection artifact
digests, exact authority placement, `E'`, `P''`, the negative-control set, and
the distinct `FixtureDigest''`.

## Result

```text
Platform amendment:       complete offline
P'':                      reproducible
R'':                      reproducible
FixtureDigest'':          reproducible
Argo convergence:         configurable, not execution-proven
Target registration:      unresolved M0b prerequisite
Source capability gaps:   log retention and alert delivery unresolved
OpenKubes reconciler:     not required by this evidence
M0a / M0b:                NOT GRANTED
T3 / GO-1:                NOT STARTED / NOT GRANTED
Infrastructure:           NO-GO
Failure Injection:        NO-GO
```
