# Database capability — binding invariants

Read this before changing anything here. It is the short form of the rules in ADR-Platform-032 that
this code must satisfy, with the section references kept so each rule can be traced back.

Consult the ADR itself when you are changing what the contract *says* rather than what the code does,
or when a rule here is not specific enough to settle the change in front of you. This file is not a
substitute for it: the ADR records why each rule exists and what evidence decided it, and several of
these rules are counter-intuitive without that reasoning.

## Evidence semantics (ADR §5.1, §5.2, §11.1)
- Four condition dimensions, evaluated as a **set**, not a chain: `OperationalReady`,
  `ProtectionReady`, `RecoveryAssured`, `CapabilityConformant`. `DatabaseServiceReady` is **pure
  policy** over them and carries no independent truth.
- `Stale` is reachable **only from a prior `Valid`**. "Never proven" is `Pending`/`Unknown` with a
  reason. Collapsing those two destroys the distinction the model exists for.
- **Inability to observe is never a counter-proof.** Unobservable → `Unknown` + reason. Only positive
  evidence of failure → `Failed`.
- Compute independent sub-signals and **reduce once**. Never assign a state then overwrite it.
- Failed-reason precedence: `BackupUnavailable` > `ContinuousArchivingFailed` >
  `BackupFailed`/`BackupOverdue`.

## Protection's three signals (§11.1)
| signal | source | never |
|---|---|---|
| execution | `Backup` CR `phase`/`stoppedAt`/`backupId` | not proof the backup still exists |
| availability | `ObjectStore.status.serverRecoveryWindow[<serverName>]` | keyed by server — a wrong `serverName` reads another database's window |
| archiving | `Cluster.status.conditions[ContinuousArchiving]` | **not** an RPO bound (§10) — WAL age is unobservable in plugin v0.14.0 |

Never read `Cluster.status.lastSuccessfulBackup`, `firstRecoverabilityPoint`, `lastFailedBackup` or
either `*ByMethod` field: deprecated, and unset for plugin backups. The identically-named
`ObjectStore` window fields are legitimate — the ban is on reading them *from the Cluster*.

### Name enumeration cannot be confined by policy (§13 finding 4)
Barman's HeadBucket needs **bucket-level `s3:ListBucket` with no `s3:prefix` condition** — asserted
in `minio-provisioning-check.py`, which requires that statement to carry exactly
`{Sid, Effect, Action, Resource}`. So every identity holding the source policy can enumerate every
object **name** in that bucket. Prefix isolation confines `s3:GetObject` and nothing else.

Two consequences, both asserted rather than described. A Sid must not claim prefix-scoped listing —
all three policies shipped saying `ListOnlyThe…Prefix` while listing bucket-wide. And **a SEPARATE
BUCKET is the precondition** for name isolation, not a separate prefix: the drill writes to
`ok-db-drill`, never into `ok-db-backups`. Adding a second cluster to the shared backup bucket
gives it visibility of the other clusters' object names — a reviewed decision, not an accident.

### Denial strings are paired with the client (§13 finding 3)
The accepted renderings (`AccessDenied`, `Insufficient permissions`, `Access Denied`) were
**measured** against one pinned `mc` build. `isolation-policy-check.py` refuses a client bump that
does not come with re-measurement, because an unrecognised denial exits as "not a permission
denial" — so a wording change would turn every real refusal into a probe failure. The check targets
the ACCEPTANCE block specifically, not the inconclusive-causes filter above it: slicing across both
let a string deleted from one still be found in the other.

Availability correlation is **window containment**, asymmetric:
`first > stopped` → `Failed/BackupUnavailable`; `stopped > last` → `Unknown` (not caught up);
`first > last` → `Unknown` (incoherent).

## Recovery evidence (§11.2)
`RecoveryAssured=Valid` requires an **admitted** `RestoreVerified` CR on the management plane, bound
by Database UID + source Cluster UID + system identifier + backup UID + resolved store tuple +
digests. Its *creation* by the operator group is the authority action (§7). `validUntil =
completedAt + class.maxAge`. Never trust `checks[].result: PASS` on its own.

- The in-restore capability conformance probe does **not** couple `RecoveryAssured` to
  `CapabilityConformant`. They attest different subjects — the probe inside the disposable recovery
  environment speaks about *that backup's* restorability, the `CapabilityConformant` probe speaks
  about the *live primary* — and they carry different temporal semantics: `RecoveryAssured` is pinned
  to one backup + UID, while §6.3 requires `CapabilityConformant` to be re-proven after every
  upgrade. `RecoveryAssured=Valid` alongside a live `CapabilityConformant=Failed` is a coherent pair,
  not a contradiction. The set in §5.1 stays a set.
- The capability probe **MUST be side-effect-free** — its DDL runs inside a transaction it rolls
  back. This is an **admissibility term, not hygiene**: it is what stops the in-restore run from
  mutating the very cluster whose restorability the artifact attests. Artifacts therefore record
  `extensionsAfterRollback` and `probeTablesRemaining`, and residue makes an artifact inadmissible.

## Capability delivery: bundled image, not image volumes (§13 bound 4)
A requested capability is delivered by the **bundled `standard` image**, which ships
`vector.control`. The ADR's model — a per-extension catalogued image mounted as an OCI image
volume on a `minimal` base — is the stronger design, because §6.4 governs each extension's image,
version and provenance separately. It does not work here: containerd added OCI Image Volume Source
support in **v2.1.0** (containerd#10579) and these nodes run 2.0.x, so the kubelet forwards a field
the runtime cannot handle and the instance never starts. The feature gate is necessary and not
sufficient, and enabling it took a database down for ~8 minutes.

Three things must move together, and `render-check` asserts all three:
- the catalog image (`standard` vs `minimal`)
- the `images.cnpg.io/type` provenance label, which must match the image actually pinned
- the ABSENCE of both `catalog.images[].extensions` and `spec.postgresql.extensions` — declaring
  either IS the image-volume mechanism, so a bundled image plus a declaration is the one
  combination that stops the instance starting

The cost is deliberate: `standard` carries a FIXED extension set, so per-extension governance
degrades to "whatever this image ships". **Restore the catalogued model and the minimal base
together** once the nodes run containerd >= 2.1.0; the per-extension assertions are kept, guarded,
for that day rather than deleted.

## The extension has TWO names
`pgvector` is the **catalog** name — what the composed CNPG spec asks for and what CNPG echoes
back in `status.pgDataImageInfo.extensions[].name`. `vector` is the **SQL** name, what
`CREATE EXTENSION` takes. Both are correct in their own namespace, and conflating them is what
broke the status reader: it matched `vector` against a field that says `pgvector`, so
`Pending/CapabilityProbePending` was unreachable and a declared-but-unprobed extension read as
ABSENT. One `$pgvectorExtensionName` constant now drives the reader and both composed specs.

**Do not "fix" the probe to use the catalog name.** It maps them explicitly (`pgvector) EXT=vector`)
and never reads `status.pgDataImageInfo` at all — its verdicts come from `pg_available_extensions`
and from exercising the extension. That is why this bug could not mislead it: the status field was
actively wrong and the probe never asked. "Never read the operator's echo" stopped being a
principle here and became a caught defect.

## Observation freshness (§13 bound 5)
Every `evidence.*.observedAt` is a **source event** time, so it cannot say whether anyone is still
looking. `status.observation.observedThrough` is the only field that can, and a reader **MUST** treat
every dimension as unproven once it is older than `freshnessBound` — whatever state that dimension
claims. A stale observation invalidates a `Valid` exactly as much as a `Failed`.

`observedThrough` is `now` floored to `quantum` (300s), never ahead of the real observation and never
more than one quantum behind it. Flooring is not cosmetic: an unfloored instant rewrites status on
every reconcile. `freshnessBound` (15m) must stay **wider than `quantum` + Crossplane's
`--poll-interval` (1m, read from the running v2.3.3 pod)**, or a healthy platform trips its own bound;
`observation-freshness-check.py` asserts that arithmetic rather than trusting the constants.

The Composition cannot evaluate its own freshness — while it runs it is fresh by construction — so
the bound is published as data and the verdict belongs to the reader. Do not fold it into
`serviceReady`.

Why this is not optional: measured on ok-mgmt, the live `Database` XR held **one** resourceVersion
across 350s of sampling. Status is written only when it changes, so a healthy composite and a dead
one emit identical bytes.

## Credential rotation overlap (§13 bound 6)
`app` owns the database and is **NOLOGIN**; `app_a`/`app_b` are login roles granted into it, each
with its **own** Secret. Two roles means two verifiers, which is the only way an overlap can exist
at all — PostgreSQL stores one verifier per role. Pointing both slots at one Secret leaves every
`status.credentials` field looking correct while the overlap is fictional, so that case is a
negative control rather than a comment.

`overlapWindow` is a protection-class attribute: **PT1H production, PT24H development**, production
shorter because a previous credential that still authenticates is standing exposure.
`previousCredentialAccepted` is published as a boolean so the consumer reads whether the old
credential still works instead of inferring it.

**Precondition on the consumer contract, not a cluster caveat.** Adopting the pair makes `app`
NOLOGIN, so anything authenticating as `app` stops opening new sessions. Measured on ok-robotics
(2026-08-20) there is currently no such consumer — no live backends on the `app` database, no pod
referencing the credential Secret by volume or `secretKeyRef`, no VaultStaticSecret fanning it out,
and the `-r`/`-ro`/`-rw` Services are all ClusterIP, so there is no out-of-cluster path. That makes
ok-robotics a good place to exercise the cutover. Two limits on that measurement: it is
point-in-time, so a CronJob or batch importer that connects periodically would not appear (pod
*specs* were swept too, which covers anything already deployed in-cluster); and the RMF stack's
`rmf-web-rmf-server-db` is a separate deployment, checked and found unrelated rather than checked
and found safe. The residual risk is therefore **a consumer deployed later expecting `app` to be a
login role** — new consumers must target the active login role from `status.credentials.activeRole`,
never `app`.

## Composed resource names
**Renaming a composed manifest ORPHANS the previous resource.** The provider-kubernetes Object
keeps existing and simply points at a new name, so `deletionPolicy: Delete` never fires and
Crossplane deletes nothing. Observed: renaming the Pooler under OK-150 left the old
`<cluster>-rw` Pooler behind on ok-robotics, and it had to be removed by hand. Any rename needs a
decommission step planned with it — `make orphan-check` reports what is left, and deliberately
does not delete.

Orphan classification has three outcomes, and the middle one is load-bearing: scheduled backups
are `<schedule>-<timestamp>` Backups **owned** by the composed ScheduledBackup, and the platform
cannot enumerate generated names (§13 bound 3). Without walking ownerReferences, three healthy
daily backups on ok-robotics were reported as garbage.

A `Pooler`'s name becomes its **Service** name, and CNPG already owns `<cluster>-rw`, `-ro` and `-r`
for the Cluster. No composed object may take one of those names — it can never acquire ownership, and
the symptom is a silent `phase=inactive` with a recurring `InvalidOwnership` warning, not a failure
anyone is paged for. `render-check.py` refuses any composed manifest named after a Cluster Service.

## Isolation (§11.3)
Read-only source, isolated write destination, compared on **resolved effective values** (the plugin's
`serverName`, not the requested name). A write denial must be an authenticated permission denial with
the raw client response recorded and the object confirmed absent; transport/credential/not-found
errors are **inconclusive**, not denials. Prefix isolation confines *data access*, not object *names*.

## Authority
Claimants never choose their backup endpoint, credential Secret, or target cluster. The
`$backupStores` registry in `composition.yaml` is platform-side and fails closed for unregistered
clusters. `clusterRef`/`namespace` are portable syntax; authorization is the admission tuple list.

## House rules learned the hard way here
- A check that cannot fail is the defect. Negative controls must mutate the **input** and re-render —
  mutating the render's own output only proves string comparison works.
- Validate manifests against an API server (`make api-acceptance-check`), not by reading your own
  YAML: a CRD certified by a file-reading check was rejected by every API server.
- Assert on a system's real response, never on a string this code produced (`mc` never emits
  `AccessDenied`; it says `Insufficient permissions to access this path`).
- A declaration echoed back in status is not evidence of function (CNPG reports an extension as
  configured on clusters where `CREATE EXTENSION` fails).
