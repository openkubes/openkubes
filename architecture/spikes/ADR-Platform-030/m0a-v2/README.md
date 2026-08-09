# M0a v2 — CAAPH fixture-binding refresh

**Ticket:** OK-141

**Baseline:** `main` at `658ea799336adb1c507c7f3635f62a5ea4aa6c3c`

**Prepared:** 2026-08-09

```text
Protocol state:     BLOCKED
M0a:                NOT GRANTED
GO-1:               NOT GRANTED
Infrastructure:     NO-GO
Failure injection:  NO-GO
```

This additive directory refreshes only the M0a binding after Phase-R-v4 and
T3-v3 superseded the previous fixture for future planning. It does not modify
the historical `m0a/` checkpoint, install CAAPH, submit a `HelmChartProxy`,
create a workload Cluster, or grant M0a/GO-1.

```text
FixtureDigest'''  sha256:a2ae3437…a7f936f6
R'''              sha256:636fe234…3128a16e
E'                sha256:2a849d69…2c213300
Candidate digest  sha256:7fd0a083…8e257fb
```

`E'` and all CAAPH/chart semantics remain unchanged. Only the current Cluster
intent and execution-fixture carriers changed, so the candidate receives a new
identity without changing its desired Helm release.

## Read-only findings

The 2026-08-09 `ok-mgmt` snapshot established:

- three `linux/amd64` Nodes running Kubernetes v1.34.1;
- CAPI v1.13.4 and cert-manager v1.20.1 controllers available;
- no CAAPH API resources, CRDs, or controller installed;
- CAPI `ClusterResourceSet` APIs are present but are not CAAPH;
- the candidate CAAPH controller image has a resolved `linux/amd64` digest;
- the official Cilium 1.19.6 OCI chart content is byte-identical to the chart
  artifact bound by `E'`.

CAAPH v0.6.4 accepts repository, chart name, and version, but has no API field
for an expected chart content digest. Therefore the exact chart can be proven
by independent registry/content evidence, but it is not controller-enforced by
the `HelmChartProxy` desired state.

```text
official OCI manifest     sha256:b8d600c5...833e75f9
OCI chart content layer   sha256:21c43cf5...f1c9179
fixture chart artifact    sha256:21c43cf5...f1c9179

content equality          proven read-only
CAAPH digest enforcement  unavailable in v0.6.4 API
```

This distinction is fail-closed. A tag or an OpenKubes annotation is not proof
that CAAPH fetched the expected bytes.

## Files

- `m0a-protocol-v2.yaml` binds the current fixture, historical installation inventory,
  artifact-resolution chain, blockers, disabled phases, and later acceptance.
- `../m0a/caaph-installation-inventory.yaml` records the exact upstream release asset
  and expected Kubernetes object inventory.
- `../m0a/caaph-rbac-review.yaml` records the controller's cluster-wide sensitive
  capabilities and the narrower submitter boundary that still must be rendered
  and proved.
- `../m0a/submitter-role-candidate.yaml` remains the bounded namespace Role candidate. No
  RoleBinding exists because the short-lived executor identity is unresolved.
  RBAC cannot by itself bind `create` to one object digest.
- `helmchartproxy-v4-candidate.yaml` is current-fixture-bound but explicitly
  not authorized for submission. It is a valid candidate object, so its
  `blocked-no-go` annotation is evidence metadata, not a Kubernetes safety
  control.
- `verify_m0a_protocol_v2.py` and `tests/test_m0a_protocol_v2.py` enforce the
  fail-closed invariants offline.
- `m0a-protocol-v2.sha256` is informational document identity only. It grants no
  authority.

## Boundary

M0a may later prove only the CAAPH prerequisite:

1. exact reviewed controller installation and RBAC on `ok-mgmt`;
2. controller/API health and restart/retry behavior;
3. exact OCI resolution and retained content evidence;
4. one current-fixture `HelmChartProxy` selecting exactly one current Cluster;
5. one controller-owned `HelmReleaseProxy` with current-generation evidence.

M0a does not authorize GO-1 and does not claim generic repair of arbitrary
Helm-rendered resource drift. Network runtime truth remains owned by Cilium and
Kubernetes; `NetworkReady` remains a bounded evaluation concern.

Any later closure of a blocker changes the protocol and requires a new digest,
review, and explicit authorization.
