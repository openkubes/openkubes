# OK-141 Phase-R v5 Authority-Routing Amendment

Status: **read-only complete; `NO-GO`**

## Finding

The first bounded GO1-L lifecycle submission exposed a missing semantic input in
Phase-R v4: its projected `KubevirtCluster` did not identify the external KubeVirt
provider cluster. CAPK therefore followed its local-provider default and attempted
to provision the control-plane LoadBalancer on `ok-mgmt`, not on `ok-infra`.

This finding does not establish a MetalLB failure on `ok-infra`. The live partial
state is preserved, and no repair, retry, cleanup, HCP/HRP submission, Cilium
convergence, Platform convergence, GO-1, or failure injection is authorized by this
amendment.

## Additive correction

Phase-R v5 adds an explicit, semantic provider-authority identity:

```text
OpenKubes contract R''''
  infrastructure.providerAccess
    managementPlane: ok-mgmt
    providerPlane:   ok-infra
    mode:            external-cluster-secret
    secretRef:       disposable-ok141/external-infra-kubeconfig-disposable-ok141
                         |
                         v
KubevirtCluster.spec.infraClusterSecretRef
```

The reference is projected by the pinned `ok-cluster` source at merge commit
`c4bb72e368bdedb92d75485ce9972d86e8a75210`. The credential Secret itself is not
part of the public contract, projection, or fixture. Its materialization remains a
separate, mutation-gated security prerequisite.

## Authority boundary

The object split is unchanged:

- `ok-mgmt`: eight CAPI/CAPK/Talos lifecycle objects and the single lifecycle
  writer;
- `ok-infra`: three provider-runtime/golden-image prerequisites;
- credential material: absent from Phase-R v5 and public Evidence.

Phase-R v5 fails closed if the provider reference is absent or inconsistent, if a
credential Secret enters either projected object set, if CAPI lifecycle resources
escape to `ok-infra`, or if a pinned source/artifact identity changes.

## Identity and compatibility

Phase-R v5 supersedes v4 only for future execution planning. Phase-R v1-v4 remain
valid historical Evidence and are not mutated.

```text
R''''             sha256:166504ae61fd558d391daedde50986cbc7a28f5f4e9d57f4acbd0433b448aa0f
E'                sha256:2a849d69e9c64344e907c1bce3bb1abf3d8f77217377081a5be055d62c213300
P'''              sha256:b0f25c639a45d895b889997f5ecc2325db45dd5d51b0684998c94d5e17bd47bf
FixtureDigest'''' sha256:7536456a762880a78a37dcba76a5f3f0628140bd37b55d5fd62273c64e4cc3eb
```

The new `R` and FixtureDigest reflect corrected provider-routing semantics. `E` and
`P` are unchanged because this amendment does not alter Enablement or Platform
desired state.

## Authorization state

```text
Phase-R v5:          offline amendment only
Live partial state:  preserved
Secret materialize:  NOT GRANTED
Repair / retry:      NOT GRANTED
GO-1:                NOT GRANTED
Failure injection:   NOT GRANTED
```
