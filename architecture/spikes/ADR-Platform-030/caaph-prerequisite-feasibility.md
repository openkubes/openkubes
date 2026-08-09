# T2a — CAAPH Prerequisite Feasibility

**Ticket:** OK-141

**Baseline:** `main` at `3f42456`

**Evaluated upstream:** CAAPH `v0.6.4` at `825662962a26dc339f3871184c91ed4bd2f83a4f`

**Evaluation date:** 2026-08-09

**Infrastructure mutation:** `NO-GO`

**Failure injection:** `NO-GO`

## Question

Can the existing Cluster API Add-on Provider for Helm (CAAPH) operationalize
the Phase-R-v2 enablement revision `E'` without introducing a second
OpenKubes-owned Helm or CNI lifecycle loop?

## Bound input

```text
R'             sha256:d49e844113bdd96868eb9dec2d6672dfcc98ccb7a0bd43f2c6b53aabc2adda62
E'             sha256:2a849d69e9c64344e907c1bce3bb1abf3d8f77217377081a5be055d62c213300
FixtureDigest' sha256:b27bb7c8e959e2c1028fcc0822755caa795ce21432344a64a62474abeb7f9f2b
Cilium chart   1.19.6
Chart digest   sha256:21c43cf53841f9ab0375047d95aa4c64051ea52bbd2c679416e6408f5f1c9179
Values digest  sha256:a02a2a8b5c5213c86e482ef7421884281d00d3bae1f27c34d67b3726df12d410
```

T2a does not alter these identities. The candidate object carries them as
correlation evidence; CAAPH does not interpret OpenKubes annotations.

## Result

```text
CAAPH API and CAPI contract fit           Configurable
Management-plane placement               Defined: ok-mgmt
HelmChartProxy shape                      Defined offline
HelmReleaseProxy projection               Deterministically assertable
Target selection                          Configurable; runtime UID proof required
E' values/release projection              Reproduced offline
Immutable chart artifact binding          Still unresolved
Controller installation and RBAC          Missing; M0a prerequisite
Bootstrap ordering                        Supported in principle; live proof missing
Restart/error retry                        Existing controller behavior; live proof missing
Requested release update convergence      Existing mechanism configurable
Arbitrary live Kubernetes-object drift    Not provided by this mechanism
NetworkReady proof                        Out of scope / still unresolved

T2a overall                               Configurable with blocking prerequisites
New OpenKubes enablement reconciler        Not required
M0a                                       NOT GRANTED
GO-1                                      NOT GRANTED
```

This is not a declaration that CAAPH is sufficient in production. It is a
bounded feasibility result and a concrete specification for a later M0a proof.

## Authority and placement

CAAPH must run on `ok-mgmt`, where the CAPI `Cluster`, its standard workload
kubeconfig Secret, and the other lifecycle resources live. It must not be
installed as a second CAPI lifecycle authority on `ok-infra`.

```text
ok-mgmt
├── CAPI Cluster disposable-ok141
├── HelmChartProxy disposable-ok141-cilium
├── generated HelmReleaseProxy
└── CAAPH controller
        │ workload kubeconfig
        ▼
disposable workload cluster
└── Helm release cilium in kube-system
```

The v0.6 release series declares the CAPI `v1beta2` contract. CAAPH v0.6.4 also
builds against the CAPI v1.13 generation, which is a plausible fit for the
observed `ok-mgmt` CAPI v1.13.4. Only installation and reconciliation evidence
can establish actual compatibility.

Sources:

- [CAAPH v0.6.4 release](https://github.com/kubernetes-sigs/cluster-api-addon-provider-helm/releases/tag/v0.6.4)
- [CAAPH release-series metadata](https://github.com/kubernetes-sigs/cluster-api-addon-provider-helm/blob/v0.6.4/metadata.yaml)

## Concrete offline objects

The non-submittable candidate is stored at
[`harness/candidates/caaph-v0.6.4/helmchartproxy-candidate.yaml`](harness/candidates/caaph-v0.6.4/helmchartproxy-candidate.yaml).
It fixes:

- namespace `disposable-ok141`;
- existing Phase-R-v2 Cluster labels as the selector;
- chart, version, release name, release namespace, strategy, and exact values;
- bounded Helm install/upgrade/uninstall options;
- full `R'`, `E'`, fixture, chart, and values identities as annotations.

Its repository is deliberately `oci://registry.invalid/...`. The object cannot
become a valid submission until a reviewed immutable source is bound and the
later protocol is re-canonicalized. The candidate contains no credential data.

CAAPH creates the per-Cluster `HelmReleaseProxy`; OpenKubes must not submit a
competing object. The expected semantic projection is stored at
[`harness/candidates/caaph-v0.6.4/expected-helmreleaseproxy.json`](harness/candidates/caaph-v0.6.4/expected-helmreleaseproxy.json).
The generated Kubernetes name is intentionally not treated as identity.

Source: [HelmChartProxy to HelmReleaseProxy construction](https://github.com/kubernetes-sigs/cluster-api-addon-provider-helm/blob/v0.6.4/controllers/helmchartproxy/helmchartproxy_controller_phases.go)

## Target selection and fail-closed acceptance

A `HelmChartProxy` selects CAPI Clusters only in its own namespace. T2a reuses
the exact existing Phase-R-v2 labels instead of modifying the frozen T1
projection. Namespace plus selector is an addressing mechanism, not identity
proof.

M0a and GO-1 acceptance must therefore require:

```text
matchingClusters == exactly one
AND selected Cluster namespace/name are exact
AND selected Cluster UID equals the UID observed for this run
AND exactly one HelmReleaseProxy points to that Cluster
AND HelmReleaseProxy controller owner is the expected HelmChartProxy
AND current observedGeneration is proven
```

`HelmChartProxy Ready=True` alone is insufficient: an empty selected set can be
operationally valid for the controller but cannot prove that `E'` was applied to
the intended Cluster.

## Revision carriers

CAAPH natively carries chart name, repository URL, chart version, rendered
values, Helm release status, and an integer Helm release revision. The integer
revision is an operation counter and is not `E'`.

The candidate carries full `E'` and its inputs as annotations so the evidence
collector can correlate them. That proves only transport:

```text
E' annotation present
!= chart artifact resolved correctly
!= release applied correctly
!= NetworkReady
```

The generated `HelmReleaseProxy` does not copy arbitrary `HelmChartProxy`
annotations in v0.6.4. Correlation must therefore retain the HCP UID, HRP
controller owner reference, exact HRP spec, current conditions, and independently
observed Helm/workload evidence.

## Immutable chart source blocker

The Phase-R fixture binds a local chart artifact digest. CAAPH v0.6.4 exposes
`repoURL`, `chartName`, and `version`, but no chart-digest field. A versioned OCI
tag alone is not cryptographic proof that the controller fetched the bound
artifact.

Before M0a can be considered, the source model must bind all of the following:

```text
controller-reachable OCI registry
reviewed TLS and credential path
immutable-tag or equivalent registry enforcement
resolved OCI manifest/content digest
proof that the resolved artifact equals the fixture chart digest
retained raw registry-resolution evidence
```

If the registry cannot supply this proof, the CAAPH candidate fails closed. An
OpenKubes annotation asserting the digest is not a substitute for registry or
content evidence.

Source: [HelmChartProxy API fields](https://github.com/kubernetes-sigs/cluster-api-addon-provider-helm/blob/v0.6.4/api/v1alpha1/helmchartproxy_types.go)

## RBAC and credentials

CAAPH's upstream controller role is cluster-scoped. It can read Secrets; watch
CAPI Clusters and provider/bootstrap/control-plane objects; create and update
HCP/HRP resources and their status/finalizers; and perform token and subject
access reviews. This is broader than namespace-only add-on submission and must be
reviewed as an M0a security prerequisite.

OpenKubes submitter permissions should remain narrower:

```text
target namespace HCP create/get/update/patch/delete
plus only the already-authorized Contract-to-CAPI projection permissions
no workload cluster-admin kubeconfig exposed to the submitter
no generic Secret read
no HelmReleaseProxy writer competing with CAAPH
```

OCI credentials and a private CA, if required, must be Secret references on
`ok-mgmt`; no secret value belongs in Git or the evidence bundle. The evidence
bundle may retain only Secret name, namespace, key name, UID/resourceVersion if
approved, and redacted access results.

Source: [upstream CAAPH controller role](https://github.com/kubernetes-sigs/cluster-api-addon-provider-helm/blob/v0.6.4/config/rbac/role.yaml)

## Bootstrap ordering

The HelmReleaseProxy controller waits until CAPI reports the control plane as
initialized and then obtains the standard workload REST configuration. It does
not wait for workload Nodes to become Ready, so it can in principle install the
CNI during the pre-network bootstrap window.

That removes the basic CNI scheduling cycle but does not prove the full path.
M0a must still demonstrate:

1. workload API reachability from the CAAPH controller failure domain;
2. creation of the HRP after Cluster selection;
3. Cilium installation before Node readiness depends on it;
4. conditions and generations remain attributable to the current HCP/HRP;
5. failure remains visible and retryable rather than being reported as success.

Source: [HelmReleaseProxy Cluster/API readiness path](https://github.com/kubernetes-sigs/cluster-api-addon-provider-helm/blob/v0.6.4/controllers/helmreleaseproxy/helmreleaseproxy_controller.go)

## Restart, retry, and drift semantics

Controller-runtime retries reconciliation errors, watched object events enqueue
work, and the manager defaults to a ten-minute sync period. Controller restart
therefore does not make a running executor process authoritative. Live restart
and retry behavior remains an M0a evidence requirement.

The term `Continuous` needs a strict boundary. CAAPH v0.6.4 continuously aligns
the selected Cluster set and requested Helm release specification. Its Helm
upgrade decision compares:

- stored Helm chart metadata version;
- failed Helm release status; and
- stored Helm values against requested values.

It does not diff every live Kubernetes resource rendered by the release.
Out-of-band deletion or mutation of a Cilium object may therefore remain
undetected when Helm's stored version, values, and release status are unchanged.

Consequently:

```text
HCP version/values/selection drift       owned by CAAPH
failed/pending Helm release recovery     handled/retried by CAAPH, to prove live
arbitrary rendered-resource drift        not guaranteed by CAAPH v0.6.4
Cilium runtime/datapath convergence      owned by Cilium controllers
NetworkReady evaluation                  separate bounded evidence concern
```

The earlier read-only hypothesis that CAAPH supplies generic Helm-rendered
resource drift correction was too broad. T2a narrows it to requested release
specification and Helm-state convergence.

Sources:

- [default manager sync period](https://github.com/kubernetes-sigs/cluster-api-addon-provider-helm/blob/v0.6.4/main.go)
- [Helm upgrade decision](https://github.com/kubernetes-sigs/cluster-api-addon-provider-helm/blob/v0.6.4/internal/helm_client.go)

## Deletion boundary

With `Continuous`, deselection or HCP/HRP deletion drives Helm uninstall through
finalizers. This is existing CAAPH ownership, not OpenKubes lifecycle ownership.
Deletion ordering when the target Cluster/API is already unavailable must be
tested separately and is not authorized by M0a or GO-1 create-only scope.

## M0a prerequisites

No CAAPH CRDs or controller are currently part of the observed OpenKubes
management baseline. A later, separately authorized M0a may be proposed only
after these values are exact and reviewed:

1. CAAPH release and image digest;
2. installation method and rendered management-plane object digest;
3. namespace, watch namespace, watch-filter value, and sync period;
4. reviewed ClusterRole/Bindings and service account;
5. immutable registry URI, TLS trust, credential references, and content proof;
6. controller-to-workload-API network path;
7. candidate HCP with the `.invalid` sentinel removed;
8. positive and negative observations, abort conditions, and recovery path.

Changing any bound value requires a new canonical protocol digest. Preparing or
reviewing M0a does not grant it.

## Reconciler necessity result

CAAPH supplies the corrective loop for standard Helm release desired state.
OpenKubes supplies deterministic `E'` construction, authorized projection,
correlation, and bounded evaluation. Cilium owns its runtime internals.

```text
OpenKubes Helm/CNI lifecycle loop required   No
Existing CAAPH mechanism sufficient today   Not proven
Existing CAAPH mechanism configurable       Yes, with blockers
RequiresReconciler                           none proven
```

An OpenKubes component that independently runs Helm upgrades or repairs Cilium
objects would duplicate CAAPH/Cilium ownership and cross the outcome-D reject
boundary.

## Operational state

```text
T1                   complete on main
T2a                  read-only feasibility complete locally
T2b                  not started
T3                   not started
M0a                  NOT GRANTED
GO-1                 NOT GRANTED
Infrastructure       NO-GO
Failure Injection    NO-GO
```
