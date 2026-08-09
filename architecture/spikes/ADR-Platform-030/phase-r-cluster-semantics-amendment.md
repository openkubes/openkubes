# OK-141 Phase-R Cluster-Semantics Amendment

Status: **Read-only T1 candidate complete; review pending**

Recorded: 2026-08-09

Branch: `spike/OK-141-phase-r-cluster-semantics-amendment`

Baseline: `main` at `0070a31607a58d035b691041c66c18ff5ae33a1c`

Authorization: **NO-GO**

## Why this amendment exists

The GO-1 preflight found that the merged Phase-R v1 fixture was reproducible but did
not fully identify the Cluster it would later authorize. In particular, it omitted
worker count, complete Talos/OS identity, machine resources, scheduling/provider
profile, endpoint semantics, and the exact Contract-to-CAPI projection.

The old fixture is not invalidated:

```text
phase-r-v1 FixtureDigest
sha256:a97e1e31e1f09cc44210679b48130e36edd90709d84ba3ee7b729ba5df82c9ba

disposition
valid historical evidence; superseded, not mutated
```

This amendment creates new identities rather than editing the v1 artifacts in place.

## Amended identities

```text
R'             sha256:d49e844113bdd96868eb9dec2d6672dfcc98ccb7a0bd43f2c6b53aabc2adda62
E'             sha256:2a849d69e9c64344e907c1bce3bb1abf3d8f77217377081a5be055d62c213300
P'             sha256:b46911c06ac31ed4755ffa83b0c960fafa0a23cab8442dc9eb1945df927b0665
FixtureDigest' sha256:b27bb7c8e959e2c1028fcc0822755caa795ce21432344a64a62474abeb7f9f2b
Authorization  NO-GO
```

`E'` and `P'` changed because the stable Contract identity changed from
`default/disposable-ok141` to the explicit per-Cluster identity
`disposable-ok141/disposable-ok141`. Their package/Application payloads are otherwise
unchanged. Neither profile embeds `R'`.

## Desired Cluster semantics bound by R'

The v2 Contract binds:

- Kubernetes `v1.36.2`;
- KubeVirt/CAPK infrastructure with reviewed provider profile `ok-infra` and profile
  identity `sha256:60fc84...befc89`;
- a provider-allocated IPv4 control-plane endpoint implemented by a
  `LoadBalancer` service and allocated by CAPK plus MetalLB;
- Talos `v1.9.6`, the exact schematic, boot-image digest, derived OS identity, and
  immutable Golden-Image PVC reference owned by `ok-linux`;
- one control-plane machine with 2 cores, 4 GiB memory, and 20 GiB disk;
- one worker machine with 2 cores, 4 GiB memory, and 15 GiB disk;
- scheduling on provider profile `ok-infra` / node selector `ok-infra`;
- Pod CIDR `10.40.0.0/16`, Service CIDR `10.100.0.0/20`, and the
  `datacenter-isolated-v1` boundary;
- exact references to `E'`, `P'`, and the required-condition profile.

Execution details such as kubeconfig paths, CAAPH namespace, Argo credentials,
submission Job names, or human authorities remain outside `R'`.

## Exact offline projection

The projection uses pinned source revisions:

```text
ok-cluster  430b946a43368d605c23bcf9888cc2eedad9a13a
ok-linux    49c244558279907b383cd87d0f672684ac1ed666
```

The checked-in source render is reproduced from the reviewed `ok-cluster` KubeVirt
Talos template and `ok-linux` profile. A deterministic correlation overlay adds only:

```text
openkubes.io/contract-name
openkubes.io/contract-namespace
openkubes.io/intent-revision = R'
```

The output is split by authority because the current renderer mixes lifecycle objects
with external-infrastructure prerequisites:

```text
ok-mgmt — single lifecycle writer
  Namespace
  Cluster
  KubevirtCluster
  TalosControlPlane
  TalosConfigTemplate
  MachineDeployment
  2 x KubevirtMachineTemplate

ok-infra — provider runtime / Golden-Image prerequisites
  Namespace
  Role in ok-images
  RoleBinding in ok-images
```

No CAPI lifecycle object is assigned to `ok-infra`. The `ok-mgmt` identity is an
execution/lifecycle authority bound by the projection fixture; it is not desired
Cluster semantics and therefore is not part of `R'`.

The renderer's auxiliary `cluster-v2.yaml.tpl` is explicitly excluded. It produces an
unreferenced KubeVirtMachineTemplate and is not part of the desired lifecycle graph.

Object-set evidence:

```text
renderer source       10 objects  sha256:587ae8d0...236a2910
ok-mgmt lifecycle      8 objects  sha256:a094b3bb...49cd1380
ok-infra prerequisites 3 objects  sha256:b9ec510e...d2c94f9
```

The Namespace intentionally exists in both target planes. CAPI objects and the
external KubeVirt runtime require the same per-Cluster namespace, while the clone
RoleBinding references the `default` ServiceAccount in that namespace on `ok-infra`.

## Endpoint boundary

No fixed host IP is placed in `R'`. The desired semantic is a provider-allocated
IPv4 `LoadBalancer` endpoint. The exact address is runtime allocation evidence and
must be correlated after CAPK/MetalLB reconciliation. Pod and Service CIDRs remain
fixed disposable-test semantics.

## What is and is not proven

Proven offline:

- equivalent v2 Contracts reproduce the same `R'`;
- worker count, resource, OS identity, or provider identity changes produce a new
  `R'`;
- the pinned sources reproduce the exact management and infrastructure object sets;
- every projected object carries the exact `R'`;
- the authority map fails closed on membership, digest, source, or identity changes;
- the frozen v1 harness still reproduces the old FixtureDigest; and
- the combined v1/v2 suite passes 17 tests.

Not proven:

- that the resources can be admitted or reconciled by the live controllers;
- that the `external-infra-kubeconfig` and provider permissions are sufficient;
- CAAPH installation, immutable Cilium artifact reachability, or `E'` convergence;
- an authorized Argo control plane, target registration, or `P'` convergence;
- runtime endpoint allocation, Cluster readiness, deletion, or recovery; or
- any infrastructure mutation.

The v2 tool is an evidence harness. It defines and verifies the expected projection;
it must not become a second production Contract-to-CAPI compiler. A later production
submission mechanism must reproduce these bytes/semantics from one authoritative
implementation.

## Next boundaries

T1 ends here. The following remain separate:

```text
T2a  CAAPH mechanism prerequisites and any separately authorized M0a gate
T2b  GitOps placement/registration prerequisites and any M0b gate
T3   new go1-protocol-v2.yaml built from the reviewed v2 fixture
```

The historical `go1-protocol-v1.yaml` remains blocked. This amendment grants neither
`M0a`, `M0b`, nor `GO-1`.

```text
GO-1:              NOT GRANTED
Infrastructure:    NO-GO
Failure Injection: NO-GO
RequiresReconciler: none proven
```
