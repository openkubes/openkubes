# Database capability — binding invariants

Read this before changing anything here. It is the short form of the rules in
ADR-Platform-032 that this code must satisfy. Read the ADR itself only when this file is
insufficient or when you are changing what the contract *says* rather than what the code does — it is
~1,000 lines and re-reading it in full is rarely the cheapest way to answer a question.

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
