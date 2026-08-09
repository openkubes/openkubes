# Enablement E and NetworkReady Observation

**Ticket:** OK-141

**Baseline:** `main` at `bf576c8`

**Observation date:** 2026-08-09

**Mode:** read-only

**Infrastructure mutation:** `NO-GO`

**Failure injection:** `NO-GO`

This document records the current Cilium enablement path, available add-on
mechanisms, and runtime network signals. It does not define a new OpenKubes API,
select an add-on controller, or treat runtime health as revision provenance.

## Safety and sensors

Repository observations covered:

- `ok-cluster/Makefile`;
- `ok-cluster/scripts/prepare_cilium_chart.py`;
- `ok-cluster/scripts/flatcar_lifecycle.py`;
- `ok-cluster/scripts/talos_golden_lifecycle.py`;
- rendered Cilium values and existing OK-128/OK-130 evidence;
- the ADR-030 revision and condition evidence already on `main`.

Live observations used read-only API and Helm metadata queries against:

- `ok-infra`, where the observed CAPI objects and add-on-capable management
  controllers currently run;
- `ok-mgmt`, for comparison;
- workload cluster `ok-ai`.

No Secret payload or rendered Helm manifest is retained in this evidence. No
resource was created, patched, deleted, restarted, or otherwise mutated.

## Current desired input

The current `ok-cluster` path constrains Cilium more strongly than an unpinned
interactive Helm command:

```text
chart version   cilium-1.19.6
chart SHA-256   21c43cf53841f9ab0375047d95aa4c64051ea52bbd2c679416e6408f5f1c9179
values          OS/profile-specific flags rendered or passed by the lifecycle path
operation       helm upgrade --install
```

The chart acquisition helper verifies the digest before installation. Talos and
Flatcar use different values because their API endpoint and host integration
requirements differ. Existing adoption evidence also records the chart digest,
rendered values identity, image digests, and readiness milestones.

This is enough to construct an immutable semantic revision candidate, for
example from a canonical tuple of profile identity, chart digest, normalized
values, and compatibility policy. That function does not currently exist as an
authoritative enablement root and the result is not projected into CAPI, Helm, or
Cilium objects as `E`.

## Current execution and ownership

The normal CNI path is procedural:

```text
make bootstrap / make install-cni / lifecycle script
  -> verify local chart digest
  -> helm upgrade --install cilium
  -> wait for Cilium and Nodes
  -> process exits
```

Helm persists release history in the workload cluster, but no Helm controller
continuously compares that release with the repository's pinned chart and
values. The deployed DaemonSet, Deployment, and ConfigMap are labelled and
annotated as Helm-managed; they do not have a Helm controller owner that would
recreate a deleted top-level resource after the command exits.

Cilium's own controllers continuously reconcile Cilium-internal state and agent
behavior. They do not own the higher-level declaration that this Cluster must
run the reviewed OpenKubes Cilium profile at semantic revision `E`.

## Installed management mechanisms

At observation time:

- `ClusterResourceSet` and `ClusterResourceSetBinding` APIs were served on both
  management APIs, but no objects existed;
- no Cluster API Add-on Provider for Helm controller or
  `HelmChartProxy`/`HelmReleaseProxy` API was installed;
- Argo CD ran on `ok-infra`, but its Applications were unrelated to workload CNI;
- no Argo CD remote-cluster registration was observed for `ok-ai`;
- no Argo CD, Flux, HelmRelease, or other add-on API was served on `ok-ai`.

Installed API availability therefore does not establish a current enablement
owner.

## Live `ok-ai` Helm identity

The workload Helm inventory reported:

```text
release       cilium
namespace     kube-system
status        deployed
Helm revision 2
chart         cilium-1.19.6
app version   1.19.6
```

Helm revision `2` is an operation counter. It is not semantic revision `E`, is
not linked to OpenKubes intent `R`, and does not by itself identify the chart
artifact digest or normalized values.

`status=deployed` proves that the Helm operation completed. It does not prove
that networking remains functional after the operation.

## Live runtime signals

The following independent runtime signals were current on `ok-ai`:

| Source | Observed state |
|---|---|
| Cilium DaemonSet | generation `1`, observedGeneration `1`, desired/current/ready/available `4/4/4/4` |
| Cilium operator Deployment | generation `1`, observedGeneration `1`, ready/available `1/1` |
| Cilium agent image | `v1.19.6` with an immutable image digest |
| Cilium operator image | `v1.19.6` with an immutable image digest |
| Cilium ConfigMap | Helm-managed and consistent with the observed Talos profile values |
| four Nodes | `Ready=True` |
| four Nodes | `NetworkUnavailable=False`, reason `CiliumIsUp` |

These sources make runtime network health observable. They remain insufficient
for an ADR-030 success statement because no current source proves that they
belong to the requested `E`, and no profile-defined end-to-end functional probe
was observed as a durable current signal.

## Minimum semantic distinction

```text
chart/version present
  != desired E accepted

Helm release deployed
  != desired E continuously converged

DaemonSet 4/4
  != NetworkReady

NetworkUnavailable=False
  != profile-required functional paths verified

runtime healthy now
  != current-generation NetworkReady proof
```

## Raw factual conclusions

1. A reproducible Cilium artifact and values identity already exists in local
   implementation and evidence.
2. No durable root currently declares semantic enablement revision `E` and links
   it to intent `R`.
3. The current Helm CLI path is non-authoritative after its process exits.
4. Cilium continuously owns its internal runtime, but not the OpenKubes profile
   selection or semantic revision.
5. Runtime sources needed for a strong `NetworkReady` evaluation are largely
   present and generation-aware.
6. A durable, profile-defined functional probe and current correlation to `E`
   were not observed.
