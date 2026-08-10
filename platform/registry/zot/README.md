# registry-default — zot on ok-shared

This shelf implements ADR-Platform-028's `registry-default` profile for the `datacenter` envelope. It deploys zot on `ok-shared` with TLS passthrough, central Keycloak OIDC, repository authorization, authenticated metrics registration, reproducible OCI conformance checks and an interim off-cluster OCI export/isolated restore drill.

Start with [runbooks/zot-bootstrap.md](runbooks/zot-bootstrap.md). The supported operator entrypoint is this directory's `Makefile`; it deliberately consumes the pinned local chart checkout at `../../../../zot/charts/zot` and never fetches a chart at runtime.

## Design choices

The profile owns two Keycloak groups:

- `registry-writers` has read/create/update/delete on `openkubes/human/**`.
- `registry-readers` has read-only access on `openkubes/human/**`.

They are reconciled by `make oidc-client`, not added to Keycloak's global `PLATFORM_GROUPS`. The groups express zot repository policy rather than a platform-wide identity baseline; adding them to Keycloak's `PLATFORM_GROUPS` would make the identity shelf own a consumer-specific authorization vocabulary. The existing `platform-admins` group remains zot's explicit admin policy, but the acceptance proof uses the two profile groups above.

The complete zot JSON has one authoritative home: `values-ok-shared.yaml` under `configFiles.config.json`. The chart renders that value into its ConfigMap. There is no second `config.reference.json` and no separately templated ConfigMap to synchronize.

OIDC uses:

- issuer `https://keycloak.ok-shared.internal/realms/openkubes`;
- `externalUrl` `https://registry.ok-shared.internal`;
- redirect URI `https://registry.ok-shared.internal/zot/auth/callback/oidc`;
- a persisted `sessionKeysFile` from Secret `zot-oidc`;
- `apikey: true`, so a human who completed central browser OIDC can create a zot-scoped API key for Docker, ORAS or Helm.

`externalUrl` is required for the callback zot constructs behind the externally visible TLS-passthrough route. `sessionKeysFile` is required operationally so restarts do not invalidate all signed/encrypted browser sessions; it is not a substitute for `externalUrl`.

## Credential model

No credential value is committed. `make identities` creates these Kubernetes Secrets out of band if absent and preserves them on rerun:

- `zot-htpasswd`: distinct machine publisher, read-only puller and metrics identities, plus the bcrypt htpasswd file;
- `zot-conformance-identities`: dedicated central-OIDC writer and reader test identities.

`make oidc-client APPROVE_OIDC_CLIENT=yes` reconciles a confidential client and writes `zot-oidc`, containing only the client credentials file and stable session keys. Secret values move through inherited descriptors, process memory or Kubernetes Secret projections; tooling does not print them or pass them in argv.

`make backup` unions two existing scoped views: `zot-machine` for
`openkubes/machine/**`, and a short-lived browser OIDC session for the dedicated conformance writer
on `openkubes/human/**`. The latter is created from the cleartext value in
`zot-conformance-identities`, remains in process memory, and is discarded after export. The backup
does not mint a zot API key or write registry auth/artifact state.

These are bootstrap Kubernetes Secrets for Increment 1. VSO/Vault escrow, Vault policies, auth mounts and roles are a later increment. Nothing in this shelf writes `ok-mgmt` or belongs in `MGMT_MAKE_TARGETS`.

Humans authenticate through central OIDC. The htpasswd identities are intentionally non-human: one scoped publisher, one scoped puller and one metrics scraper. API keys generated after browser OIDC inherit the human's group-driven zot authorization.

## Lifecycle

Run `make help` for the full target list. The aggregate order is:

```text
namespace → identities → reachability → oidc-client → zot → metrics → post-check
```

Any target that reconciles the central Keycloak realm is labelled `APPROVAL:` and requires `APPROVE_OIDC_CLIENT=yes`. Every teardown target requires `CONFIRM=yes`. The aggregate teardown retains the PVC/artifact data and central Keycloak objects; `teardown-data` is a separate irreversible operation.

The chart must be exactly `zot-0.1.122`, with runtime chart files clean. Its `appVersion` is v2.1.18, while the runtime image is explicitly pinned to v2.1.20 and its immutable digest in `values-ok-shared.yaml`.

## Backup and recovery boundary

`make backup BACKUP_DIR=<operator-retained-directory>` exports through the OCI Distribution API;
it does not shell into zot, mount its RWO PVC, stop the live registry or copy the node-local
filesystem. Repository tags and immutable manifests are enumerated, OCI Referrers are followed,
and discovered manifests/blobs are copied into a portable OCI layout. The resulting tar is paired
with a detached JSON integrity manifest. The tar contains its source inventory; the detached
manifest records both the tar's byte size/SHA-256 and the embedded inventory's byte size/SHA-256.
The executable verifier checks those commitments and then checks each content-addressed OCI blob
against its filename before PASS.

That detects accidental truncation or alteration without the source registry. It does not provide
authenticity: replacement of both tar and manifest is not detectable without a separately trusted
signature. The Distribution catalog cannot enumerate an untagged, unattached manifest, and the
export is not a transaction across concurrent repository writes.

`make restore-drill` is attended and `APPROVAL:`-gated. It installs the pinned zot image as a second,
ephemeral release in a unique `zot-restore-drill-*` namespace. The destination is constructed only
through a loopback port-forward to that release's `ClusterIP` Service; no destination-registry
variable exists. The script hard-rejects the live `zot/zot` namespace/release, verifies the scratch
labels and exposure shape, restores with digest preservation, then pulls the pre-backup digest and
requires the returned bytes to hash to that exact digest. Default cleanup removes the release and
namespace. `RETAIN_SCRATCH=yes` is diagnostic-only and transfers responsibility for prompt removal
to the operator because it leaves an unmonitored second artifact copy.

OIDC/authz configuration is not copied into the content tar. The non-secret configuration is
honestly reconstructed from `values-ok-shared.yaml`, templates and Make targets in Git. Live secret
values are not reconstructible from Git: the paired htpasswd/cleartext machine identities, OIDC
client secret and session keys require sanctioned escrow or an approved recreation ceremony. This
keeps secrets out of the portable artifact and means full disaster recovery still depends on that
separate secret-recovery path.

The export directory is off-cluster relative to zot's `local-path` PVC, but its durability is an
operator property. A workstation directory proves export/restore mechanics, not production-approved
retention. This is explicitly interim under OK-138's storage decision; point the export target at
the sanctioned MinIO-backed storage when OK-81 delivers it, without introducing another object
store. See [runbooks/zot-backup-restore.md](runbooks/zot-backup-restore.md).

## Requirement-to-test mapping

| Requirement | Executable proof |
|---|---|
| Pod and Certificate Ready; TLS passthrough reaches real zot | `make post-check` asserts Pod `Ready=True`, Certificate `Ready=True`, authenticated `GET /v2/` HTTP 200 with Distribution API `registry/2.0`, and binds it to the live pod's `ReleaseTag=v2.1.20` plus pinned image ID through `--resolve` |
| Central human OIDC and groups claim | `make oidc-client` decodes a real issued token; `make oidc-conformance` repeats it and prints only `preferred_username` and `groups` |
| Repository-scoped human authz | `make oidc-conformance` proves writer push/pull, outside-prefix 403, reader pull/403 push, membership removal/new-token 403, restoration/new-token pull |
| Machine immutable-digest contract and outside-prefix denial | `make contract-job` asserts byte/digest identity **and** 403 outside the machine prefix. `make smoke` asserts byte/digest identity and that a read-only identity is denied write *inside* the prefix — that is action scoping, not prefix scoping |
| In-cluster OCI 1.1 + Referrers | `make contract-job` runs a Job with the CA mounted, then asserts push, pull, digest pull, layer bytes and Referrers descriptor structure |
| Authenticated metrics and moving push counter | `make post-check` proves unauthenticated 401/403 and authenticated 200; `make smoke` asserts this run's `zot_repo_uploads_total{repo=...}` increased |
| ServiceMonitor registration | `make metrics` admits it; `make post-check` resolves its selector against the actual Service labels and named port |
| Off-cluster artifact content and integrity | `make backup BACKUP_DIR=...` exports discovered OCI manifests/blobs and publishes a detached size/SHA-256/inventory manifest only after both detached and per-blob verification pass; `make verify-backup ...` repeats that verifier without cluster access |
| Isolated recovery and immutable identity | `make restore-drill ... APPROVE_RESTORE_DRILL=yes` restores only through a loopback port-forward to a unique scratch zot, then pulls the digest recorded before backup and hashes the returned bytes to that same digest |
| Live-registry isolation and cleanup | `make restore-drill` rejects the live namespace/release before mutation, asserts a ClusterIP-only ephemeral scratch release, and by default proves the scratch namespace was removed; the post-drill procedure compares live PVC UID/creation timestamp and reruns `make post-check` |
| Bootstrap runbook | Walk [runbooks/zot-bootstrap.md](runbooks/zot-bootstrap.md) top to bottom and retain the command transcript |
| Backup/recovery runbook | Walk [runbooks/zot-backup-restore.md](runbooks/zot-backup-restore.md) and retain the artifact, detached manifest, restore output and cleanup proof |
| Phase-1 envelope mechanics | `conformance/smoke.sh`; Referrers are structurally asserted and run IDs make the negative auth repository repeatable. `conformance/lifecycle.sh` is **not** Increment 1 evidence — it restarts the registry and needs `gcDelay` lowered from the shipped production 1h |

## What this does not prove

- It does **not** prove a kubelet/containerd image pull. The in-cluster Job proves the OCI client contract with an explicitly mounted CA. Talos containerd trust (`machine.registries.config`) and a kubelet pull remain deferred by the ticket owner.
- `make post-check` alone does **not** prove Prometheus scraped the ServiceMonitor; the separate Increment-2 live Prometheus query is that evidence. The backup/restore targets add no dashboard, log or alert coverage.
- The interim export does **not** prove production-approved retained storage unless the operator's `BACKUP_DIR` actually resides on such storage. It provides no scheduler, retention policy, replication, object lock or MinIO/S3 integration. `local-path` remains the deliberate live-storage choice pending OK-81's MinIO target.
- It does **not** provide a transactionally consistent snapshot across concurrent registry writes, and it cannot discover an untagged manifest that is neither a referrer nor otherwise exposed by the Distribution API catalog/tag surface.
- It does **not** certify registry-wide absence outside `openkubes/{machine,human}/**`. The two available identities cover those current normal prefixes; a repository created directly through the global `platform-admins` policy is invisible to both catalogs. A complete future exporter needs a distinct read-only all-repository identity.
- The interim backup process reuses the write-capable machine publisher and conformance writer because zot cannot load a new htpasswd/policy identity without the forbidden live restart. The script performs only GETs, but this does **not** satisfy ADR-Platform-028 §4.5's distinct read-only exporter identity separation.
- It does **not** authenticate the backup artifact. SHA-256 detects changed bytes against the detached manifest, but an attacker able to replace both files can create another self-consistent pair.
- It does **not** prove complete disaster recovery of secret state. Git reconstructs the rendered zot/authz/route configuration; machine/OIDC secret values still need sanctioned escrow or approved recreation.
- It does **not** prove offline transfer or upgrade/rollback.
- It does **not** escrow bootstrap credentials in Vault/VSO.
- It does **not** run the OCI Distribution conformance suite. ADR-Platform-028 §4.1 requires validation against that tooling and §8.9 makes it an acceptance criterion; Phase 1's `conformance.sh` was deliberately not ported into Increment 1, so despite the directory name no official conformance run has happened against this deployment.
- It does **not** meet ADR-Platform-028 §5's `Storage: Production-approved persistent or object storage` line merely by shipping this workflow. The live store remains `local-path`; the detached export meets that line only when the operator supplies a production-approved retained target. The interim decision is settled under OK-138 and re-points at OK-81's MinIO when available.
- It does **not** satisfy ADR-Platform-028 §4.7 (tag immutability, retention classes, deletion authorization, emergency deletion) or §4.10's alerting signals for backup age, restore-test status and certificate expiry. The machine identity currently holds `delete` across the whole `openkubes/machine/**` prefix.
- Group membership removal does **not** revoke an already-issued API key. zot binds groups into the API-key record when it is minted, so `make oidc-conformance` proves that a *new* login after removal is denied, not that existing credentials stop working.
- It does **not** satisfy all ADR-Platform-028 §8 acceptance criteria or make that Draft ADR Accepted. §8 remains unchanged until each criterion has live evidence.

## Layout

```text
Makefile                    lifecycle entrypoint and guards
values-ok-shared.yaml       sole zot JSON configuration home and chart values
manifests/*.template.yaml   namespace, identities, reachability, metrics and Job objects
tooling/                    credential reconciliation and live proof tooling
conformance/                ported Phase-1 smoke and lifecycle contracts
runbooks/zot-bootstrap.md   executable bootstrap ceremony
runbooks/zot-backup-restore.md  interim export and isolated recovery ceremony
```
