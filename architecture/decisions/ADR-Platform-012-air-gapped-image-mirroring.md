# ADR-Platform-012: Air-Gapped Image Mirroring for Talos Boot Images

**Status:** Proposed — pending three-way review (Arash / Claude / GPT)
**Date:** 2026-07-09
**Related:** OK-59, ADR-Platform-001 (contracts not components), ADR-Platform-009 (storage contract)

## Context

`ok-cluster`'s `templates/talos/cluster-base.yaml.tpl` hardcodes VM boot disk imports against a public, third-party endpoint:

```
https://factory.talos.dev/image/${TALOS_SCHEMATIC_ID}/${TALOS_VERSION}/openstack-amd64.qcow2
```

This was surfaced during OK-55 verification, when the URL intermittently returned `404` (transient Factory-side flakiness, since resolved on its own). The underlying issue is architectural, not transient: **every Talos cluster bootstrap currently requires live internet access to a service OpenKubes does not control.**

This directly contradicts the platform's own positioning:

> *Private AI · Bare Metal · Edge · On-Premises · Multi-Cloud*
> "Sovereign — runs entirely on your hardware, your network, your rules"

A genuinely air-gapped or high-trust on-premises deployment cannot depend on `factory.talos.dev` being reachable at cluster-creation time. This needs to be solved before OpenKubes can honestly claim air-gap support.

## Decision

**`ok-linux` owns the Talos boot image as a build-time artifact, published once into the platform's own storage. `ok-cluster` never talks to `factory.talos.dev` directly.**

Concretely:

1. **Golden-image pattern**, using CDI's `source: pvc` clone mechanism. `ok-linux`'s `make build PROFILE=<name>` — which already submits the schematic to Image Factory and resolves `schematic_id` — is extended to also download the resulting image once and import it into a golden `DataVolume`/PVC on the RKE2 host cluster, backed by `ok-storage-block` (per ADR-Platform-009 — no new storage mechanism introduced).
2. **`ok-cluster`'s `cluster-base.yaml.tpl` changes its `dataVolumeTemplates[].spec.source`** from `http: {url: ...}` to `pvc: {name: <golden-image>, namespace: ...}`. New VM boot disks clone from the golden PVC locally via Longhorn — no network egress required at cluster-creation time.
3. **Factory becomes a build-time dependency for `ok-linux` only.** Every `ok-cluster` `make new`/`make bootstrap` becomes fully air-gap-capable once at least one golden image has been published for the profile/version in use.

This keeps the existing contract boundary intact: `ok-linux` remains "source of truth" for Talos version/schematic/image (per its integration contract with `ok-cluster`), it just now also owns *distribution*, not only *resolution*.

## Alternatives Considered

**Internal HTTP mirror** (e.g. nginx or MinIO serving the downloaded qcow2/raw image, `cluster-base.yaml.tpl` pointed at the internal URL instead of Factory). Rejected as the primary mechanism for v1: introduces a new always-on service and a new failure domain, for no benefit over the golden-image approach on the current 2-node hardware. Not ruled out for the future — e.g. if `ok-apps` workloads need general-purpose OCI/object storage anyway, image mirroring could piggyback on that. Revisit if/when Harbor or MinIO gets adopted platform-wide for other reasons.

**OCI registry mirror** (`source: registry`, pushing the image into an internal Harbor, following the pattern `cluster-v2.yaml.tpl` already uses for the Talos *installer* image via `docker://factory.talos.dev/installer/...`). Technically viable and consistent with existing precedent in the repo. Not chosen as the default for the same reason as the HTTP mirror: it requires standing up and operating Harbor as a new dependency. Kept as the natural upgrade path if/when Harbor becomes a platform-wide need — the `source.registry` shape in `cluster-v2.yaml.tpl` can be reused directly.

**Do nothing / accept the Factory dependency.** Rejected: incompatible with the platform's own "Sovereign, on-premises" claim, and OK-55 already showed live dependency on an external, occasionally-flaky third party turns into wasted debugging time even in a *connected* environment — the risk is strictly worse air-gapped.

## Consequences

- `ok-linux` gains a new responsibility (publishing golden images), and a new build output (a DataVolume/PVC on the host cluster, not just a `schematic_id` string in `profile.yaml`). Its Makefile and docs need to grow a `make publish` (or similar) step.
- `ok-cluster`'s `cluster-base.yaml.tpl` `source:` block changes shape (`pvc` instead of `http`). This is a breaking change to the template contract — needs a version bump and a migration note for anyone with rendered cluster directories already checked into Git per the `state:`-commit convention.
- Refreshing an image (new Talos patch version, new extension, security update) now requires an explicit re-publish step in `ok-linux`, rather than happening implicitly on next download. This is a feature (reproducibility, explicit control) as much as an obligation — should be documented clearly so it isn't forgotten.
- The golden PVC's lifecycle needs a decision: is it retained indefinitely (one per profile/version, accumulating), or pruned? Out of scope for this ADR; tracked as an open question for the `ok-linux` implementation.
- No impact on `ok-storage`'s contract itself — `ok-storage-block` is consumed as-is, per its existing guarantees.

## Open Questions (for implementation, not blocking this ADR)

- Exact namespace/naming convention for golden PVCs (e.g. `openkubes-system/talos-golden-<profile>-<version>`)
- Retention/cleanup policy for superseded golden images
- Whether `ok-linux`'s `make build` should publish automatically, or remain a separate explicit `make publish` step
