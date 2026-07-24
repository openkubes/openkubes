# ADR-Platform-023: CAPI infrastructure providers as Implementation Profiles for the native cluster lifecycle path

**Date:** 2026-07-23
**Status:** Accepted

**Extends:** ADR-Platform-008
**Clarifies:** ADR-Platform-007
**Related:** ADR-Platform-001, ADR-Platform-003, ADR-Platform-017, OK-78, OK-106
**Constraint Envelope:** `datacenter`

---

## Context

ADR-Platform-008 defines `TYPE=talos-mgmt` and describes its `bootstrap-mgmt.sh` as installing "CAPI + CAPK providers" — i.e. KubeVirt is written into the described management-cluster structure. ADR-Platform-007 likewise describes both CAPI installations concretely with CAPK. At the time, CAPK/KubeVirt was the only infrastructure provider, so this was accurate.

OpenKubes is designed so that infrastructure components can be replaced without creating a new platform contract. OK-106 tests that principle within the Cluster API infrastructure-provider model: can the same native Talos cluster-lifecycle path drive a second CAPI infrastructure provider — CAPO/OpenStack — without changing the shared lifecycle. The spike (branch `ok-106-capo-provider-selection`, base `b991898`; commits `dfe8bf6`, `63f6ab7`, plus evidence) produced two statically validated results:

1. The `talos-mgmt` management-stack bootstrap can install **CAPO instead of CAPK** as the infrastructure provider, selected by the Implementation Profile (`cluster-config.yaml provider:`). Provider-specific waits and infrastructure preparation (CAPK external-infra secret vs OpenStack credential assertion) live under the selected profile.
2. A native `TYPE=talos` **workload** cluster can be rendered as a CAPO/OpenStack manifest set (`OpenStackCluster` + `OpenStackMachineTemplate`) sharing the **same** provider-neutral Talos core (`Cluster` / `TalosControlPlane` / `TalosConfigTemplate` / `MachineDeployment`). The OpenStack profile renders an Octavia managed LoadBalancer configuration for the control-plane endpoint instead of the KubeVirt MetalLB service.

Key finding: the native path already uses `TalosControlPlane`. The Kubeadm coupling exists only in the historical `capi-platform-v4.2` runner (ADR-Platform-003), which is out of scope here.

Because ADR-008 currently pins CAPK as part of the described structure, making the provider selectable is a **material extension**, not an editorial change, and therefore requires this new ADR before the branch is merged (per the ADR lifecycle convention).

---

## Decision

> On the native Talos cluster-lifecycle path, the CAPI **infrastructure provider** (CAPK/KubeVirt, CAPO/OpenStack, …) is an **Implementation Profile**, not a separate cluster-lifecycle contract. The provider-neutral Talos objects and the currently implemented native-path lifecycle behaviour are shared across profiles; only infrastructure resources, credentials, and the control-plane endpoint mechanism vary per profile. This ADR does not determine whether that shared behaviour constitutes a distinct OpenKubes lifecycle contract above CAPI.

Concretely:

- The native Talos lifecycle remains a **CAPI-based** lifecycle path.
- `CAPK/KubeVirt` and `CAPO/OpenStack` are CAPI infrastructure **Implementation Profiles**, selected declaratively via `cluster-config.yaml provider:`.
- `TalosControlPlane`, `TalosConfigTemplate`, `MachineDeployment`, and the currently implemented native-path lifecycle behaviour stay **common** across profiles.
- Provider-specific infrastructure objects, credentials, and endpoint mechanism (KubeVirt MetalLB service ↔ OpenStack Octavia managed LoadBalancer) live **under** the profile.
- `providers/<provider>/` is the **physical layout** of an infrastructure Implementation Profile — not a new architecture layer or a second contract.
- Scope is `Constraint Envelope: datacenter`.

### Scope boundary (deliberately narrow)

This ADR covers exactly two profile-selection points:

1. **Management-stack provider installation** — which infrastructure provider `bootstrap-mgmt.sh` installs into `ok-mgmt`.
2. **Workload provider portability** — which infrastructure a native `TYPE=talos` workload cluster is rendered for.

It does **not** establish **Hosting Independence** of `ok-mgmt` itself. Today a `TYPE=talos-mgmt` cluster still renders its *own* machines from `templates/talos` (KubeVirt); rendering `ok-mgmt`'s own machines via CAPO on OpenStack, and the bootstrap-and-pivot path that implies, is explicitly deferred (OK-106 Proof C / a future ADR).

The `provider:` field currently serves two distinct axes — the provider *installed into* the management cluster (`talos-mgmt`) and the provider a workload cluster is *rendered for* (`talos`). This ADR restricts its claims to those two selection points and records **separating these axes as a prerequisite before any Hosting-Independence claim** (see Consequences).

### What this does NOT decide

- It does **not** establish independence from Cluster API. CAPK and CAPO are both CAPI providers; this proves portability **within** the CAPI infrastructure-provider model.
- It does **not** establish that a distinct OpenKubes lifecycle contract exists *above* CAPI (result option 5 of OK-106 remains open, to be answered once provisioning is exercised).
- Static rendering + structural validation is sufficient to accept **this structural decision**. Any public claim of "runtime validated on OpenStack" additionally requires Create / Scale / Delete and `KubernetesReady` conformance on a real tenant.

---

## Rationale

1. **Consistent with ADR-Platform-001.** The provider-specific CAPK/CAPO objects are components and Implementation Profiles; the currently shared native lifecycle path remains above those provider-specific resources. ADR-001 does not itself specify the concrete contracts, so leaving "distinct contract above CAPI?" open is correct.
2. **Clarifies, does not rewrite, ADR-Platform-007.** The responsibility split (ok-infra bootstraps ok-mgmt; ok-mgmt operates workload clusters) is unchanged. The clarification is only that CAPK was the *first implementation* at each installation point, not part of the responsibility interface.
3. **Extends ADR-Platform-008 as required.** ADR-008 pinned CAPK into the described mgmt structure; making the provider selectable is a material extension recorded here rather than silently editing the accepted ADR.
4. **Method-consistent.** New providers should land at the Implementation-Profile / Provider-Values level; an ADR is needed here only because ADR-008 pinned CAPK.
5. **ADR-Platform-003 not overtaken.** The native path adopts lessons from the historical runner without declaring the runner's re-homing complete — ADR-003 describes re-homing as a longer, multi-repo process still in progress.

---

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Merge the spike branch without an ADR | ADR-008/007 pin CAPK into accepted structure; provider selection is a material extension requiring a new ADR before it becomes accepted architecture |
| Treat OpenStack as a new Constraint Envelope now | ADR-017: envelopes are discovered from real deployments, not invented; regulated tenancy is a governance context, not by itself an envelope |
| Model CAPK and CAPO as separate cluster-lifecycle contracts | Would contradict ADR-001 and duplicate the shared Talos lifecycle; they are infrastructure profiles under one path |
| Claim Hosting Independence now | Not demonstrated — `ok-mgmt` still renders its own machines as KubeVirt; the two provider axes must be separated first |

---

## Consequences

**Positive:**
- Infrastructure-provider portability within the CAPI model is expressed declaratively; adding a supported CAPI provider is a profile, not a lifecycle fork.
- The default remains `provider: kubevirt`; the existing KubeVirt template path remains selected by default, and the static CAPK regression checks pass. Runtime behaviour was not revalidated by this spike.
- Honest, bounded public claim; the credibility of "OpenKubes serves OpenStack" rests on structural evidence plus a clearly pending runtime step.

**Negative / trade-offs:**
- Two provider axes share one `provider:` field; until separated this must not be read as Hosting Independence.
- The spike's OpenStack template currently duplicates the provider-neutral core; long-term this needs a shared core or a structural contract test (see acceptance conditions).

**Conditions of acceptance (merge gates for `ok-106-capo-provider-selection`):**
1. This ADR (023) three-way reviewed and committed as `Accepted`.
2. Hosting-provider vs workload-provisioning-provider semantics separated, **or** ADR/claim scope explicitly limited to workload provider portability + mgmt-stack provider install (this ADR takes the latter).
3. Shared provider-neutral core, **or** an automated structural contract test proving the neutral objects of both profiles are field-equivalent (parallel kind lists alone are insufficient against drift; this test should feed the OK-78 phase/conformance model).
4. `openkubes.io/provider` removed **or** normatively defined and applied to both profiles (this ADR defines it — see below).
5. Public claim limited to static validation until real-tenant conformance exists.

### `openkubes.io/provider` (normative)

`openkubes.io/provider` identifies the CAPI infrastructure provider referenced by the labelled `Cluster` object's `spec.infrastructureRef`. Its value is the canonical lowercase `clusterctl` provider name (e.g. `kubevirt`, `openstack`). The label is **descriptive metadata derived from `spec.infrastructureRef`; it is not an independent source of truth.** It must **not** denote the workload-provisioning provider installed in `ok-mgmt`; that is a separate axis (see Scope boundary). The label must be applied consistently to both the KubeVirt and OpenStack profiles, verified by a test.

---

## Re-evaluation triggers

- A real OpenStack tenant becomes available → run Create / Scale / Delete + `KubernetesReady` conformance; only then may the public claim move to "validated on OpenStack".
- Hosting Independence pursued (`ok-mgmt` rendered on OpenStack + bootstrap-and-pivot) → new ADR; separate the two provider axes first.
- A regulated deployment demonstrates materially different environmental constraints or guarantee levels → candidate new Constraint Envelope (ADR-017).
- A structurally different consumer (imported cluster / managed Kubernetes / alternative lifecycle controller) → re-open the "distinct OpenKubes contract above CAPI?" question (result option 5).
- A third CAPI provider (CAPA/AWS, CAPZ/Azure, CAPG/GCP) adopts a profile → confirms this decision; no new ADR unless it changes a contract.
