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
