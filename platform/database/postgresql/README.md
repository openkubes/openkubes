# PostgreSQL database capability architecture spike

This directory is the OK-145 spike/prototype for the `Database` / `DatabaseClaim`
contract defined by ADR-Platform-032. It is not an installable or continuously delivered
database capability. The local models and one attended restore drill provide bounded
architecture evidence; they do not establish the current installation of this capability or
any of its providers.

## Contract boundary

The XRD keeps engine, performance, availability, connectivity, protection,
maintenance, and isolation orthogonal. Authority-adjacent values are closed enums or
fixed Secret references; the target cluster and workload namespace remain portable API
fields and are authorized by the fail-closed tuple list in
`crossplane/claim-admission-policy.yaml`. The claim-editor Role reaches
`databaseclaims` only and cannot read Secrets or manipulate composites.
The Python admission matrix models the authored tuple; it does not prove that a Kubernetes
API compiled or enforced the `ValidatingAdmissionPolicy`. The Makefile reports that real API
check explicitly as skipped.

The CNPG profile renders provider-kubernetes `Object` resources. Every Object uses the
XR's `clusterRef` as its `providerConfigRef.name`; there is no independent target-cluster
default. Stateful resources use an orphan deletion posture. Backup is the CNPG-I plugin
surface (`spec.plugins` plus an `ObjectStore` CR), not the deprecated in-tree
`barmanObjectStore` surface. Execution identity and time come from observed
`Backup.status.phase`, `stoppedAt`, and `backupId`; they never establish current
availability by themselves. Current availability comes from the plugin ObjectStore recovery
window. Deprecated Cluster backup status is never read.

## RestoreVerified evidence API

`crossplane/restoreverified-crd.yaml` defines a cluster-scoped, immutable evidence event so
Crossplane v0.9.2 ExtraResources can select it in the management-plane trust domain. Its spec
binds exact Backup, source CNPG Cluster, and Database/XR UIDs; resolved source coordinates;
requested and reached targets; timing; profile and manifest digests; the complete check profile;
isolation observations; and verifier/provider versions. The schema accepts exactly one `PASS`
for each governed v1 check and requires each result's typed observed values; a result constant
without its supporting observation is inadmissible. An incomplete or failed verification creates
no event. The required `platform.openkubes.ai/source-cluster` metadata label is the
ExtraResources selector key, not an independently trusted identity. Kubernetes cannot enforce
a root-level CEL comparison against arbitrary metadata labels, so the Composition independently
compares the selected artifact's typed `sourceClusterRef` name and UID with the observed CNPG
Cluster.

Delegated creation belongs to `oidc:database-restore-verifiers`; it receives
`create/get/list/watch` but no update, patch, or delete. The exact
`crossplane-system/crossplane` ServiceAccount receives read-only access. Kubernetes cluster
administrators can override or replace RBAC, so this delegated-authority statement does not
pretend to constrain cluster-admin authority.

## Deliberate v1 choices

- The pipeline pins only `function-go-templating:v0.9.2`. Go templating is required for
  the observed-manifest, prior-state, TTL, and policy expressions that
  patch-and-transform cannot express. `function-auto-ready` is deliberately absent:
  standard composed-resource readiness must not become a second truth that can report a
  production Claim Ready while `serviceReady` is false.
- A recovery source is the protected CNPG cluster name itself. The drill template has
  one source-identity token reused for both `bootstrap.recovery.source` and the source
  object's server folder below `destinationPath`; the render checker rejects any
  divergence. There is no separately typed alias that can silently select another
  server's WAL folder.
- `majorVersionStrategy` is closed to `blueGreen` for v1. CNPG's in-place major upgrade
  is intentionally excluded: the import-based blue/green path preserves a separately
  inspectable source and makes supervised cutover/rollback authority explicit. The
  generated Cluster also pins `primaryUpdateStrategy: supervised`.
- The pgvector allowlist lives in the platform-rendered `ClusterImageCatalog`: its
  PostgreSQL and extension images are official CNPG references pinned by SHA256 digest,
  with publisher/date/OS/type provenance labels. A Claim can request only
  `postgresql.extension.pgvector`; `Cluster.spec.postgresql.extensions` consumes the
  catalog entry and is not itself an open image-reference surface.

## Evidence semantics

Each of `operational`, `protection`, `recovery`, and `capability` reports one of
`Pending`, `Valid`, `Stale`, `Failed`, or `Unknown` plus `observedAt`; bounded evidence
also reports `validUntil` and `evidenceRef`. `Stale` is emitted only when the same
dimension has previously been `Valid` and its evidence has aged out. At t=0, protection
is `Unknown/AwaitingFirstBackup` and recovery is `Unknown/VerificationPending`; an expired
execution that was never independently proven stays `Pending`, never `Stale`.
`serviceReady` is derived only from the four dimensions. Development may tolerate
non-Valid protection while recovery is `Valid`, plus the exact initial
`Unknown/AwaitingFirstBackup` + `Unknown/VerificationPending` bootstrap pair; it does not
treat arbitrary Pending recovery evidence as ready. Production requires every dimension Valid.

Protection `Valid` requires three independent signals: completed execution for the selected
Backup, current availability of that same backup, and `ContinuousArchiving=True`. The last
signal means continuous archiving is not currently reporting failure; it does not measure WAL
age or backlog. Accordingly, v1 protection can reach `Valid`, but—as ADR-Platform-032 §10
states explicitly—`ProtectionReady=Valid` is not an RPO bound. A consumer that requires a
bounded RPO needs a future typed WAL-age observation and must not infer it from this status.

Development uses a 72h first-backup grace period and 14d initial-verification deadline;
production uses 24h and 72h. These are platform attributes, never Claim fields. The first-backup clock uses
the later of Cluster Ready and observed `ScheduledBackup.status.lastScheduleTime`; it
does not parse cron. The earliest computed deadline is retained in prior protection
status because CNPG exposes the latest, not the first, schedule time. If the schedule,
Cluster readiness, or Backup result cannot be observed, the verdict is
`Unknown/ObservationUnavailable`; a conclusively missed deadline with complete schedule,
cluster and Backup observations is `Failed/BackupOverdue`. An observed failed Backup is the
more direct counter-proof `Failed/BackupFailed`. The initial verification clock starts only after
a completed Backup and becomes `Failed/VerificationOverdue` when no first restore
verification arrives by its class deadline.

ADR-Platform-032 §5.2 maps evidence `Valid` to condition `True`, `Failed` and `Stale` to
`False`, and `Pending` and `Unknown` to `Unknown`. The current XRD exposes evidence
`state` and `reason`, but no condition-status field, so that mapped Kubernetes status is
not yet serialized by this scaffold; widening the XRD requires a separate reviewed API
change.

## Local verification

From this directory:

```bash
make validate
make render
make render-check
make claim-policy-check
make claim-authority-model-check
make claim-admission-check
make restoreverified-api-check
make evidence-status-check
make drill-validate
make drill-policy-check
make minio-provisioning-check
make restore-evidence-check
```

`make validate` wires every offline target above, including MinIO checks and generated
RestoreVerified writer/rejection fixtures, and fails if Python caches or build artifacts appear
in this capability tree. The historical pre-API artifact remains point evidence, not the current
schema fixture.

The `setup`, `bind`, and `deploy` targets remain discoverable but fail closed. ADR-Platform-032
§13 leaves the provider-kubernetes ProviderConfig and real admission proof as separate attended
management-plane prerequisites. There is no automated evidence collection, no scheduled-Backup
enumeration, and capability delivery remains unproven. Reachable local evidence states are
contract behavior, not proof that the capability is installed or continuously reconciled on a
management plane, so this spike makes no continuous delivery or production-readiness claim.

`undeploy` is not general teardown: it deletes only a Claim and leaves stateful composed objects
orphaned. It does not remove a CNPG Cluster, PVC, ObjectStore data, MinIO, operators, CRDs, or the
fixed backup referenced by historical evidence. Stateful teardown is separately approved work.

See `drill/README.md` for the restore drill's narrower proof boundary and separate
read-source/write-destination credentials.

## Prerequisite nobody writes down: the authority group must have members

`bind` delegates `DatabaseClaim` authority to the OIDC group `oidc:database-claim-editors` and then
proves both halves — the group may create its authorized claim, and may not read Secrets or create
`Database` composites directly. Those proofs are performed by **impersonation** (`--as-group`), which
works whether or not the group has any members.

Measured 2026-08-18: the `openkubes` realm on the central Keycloak contains **no human accounts** —
only zot service users. So the delegation is correct and currently unexercisable by any real person.
ok-mgmt maps `username: {claim: preferred_username, prefix: "oidc:"}` and
`groups: {claim: groups, prefix: "oidc:"}` against `https://keycloak.ok-shared.internal/realms/openkubes`,
so a real claimant needs:

1. an account in the `openkubes` realm,
2. membership of a group whose mapped name is exactly `oidc:database-claim-editors` — the `oidc:`
   prefix is part of the Kubernetes-side subject, not part of the Keycloak group name, and
3. a groups claim actually present in the issued token (a missing mapper binds nobody, silently).

Until then, `make deploy` uses `DEPLOY_USER` purely as audit attribution: impersonation does not
require the identity to exist. That is fine for a spike and dishonest to leave unsaid, because the
proofs in `bind` can otherwise be read as "a human can do this today". They cannot yet.

## Prerequisite that silently wedges provisioning: the app credential Secret

`bootstrap.initdb.secret` names `database-ok-robotics-app`, and the Composition mirrors that
Secret's `data` from `crossplane-system` on ok-mgmt to the workload namespace **by reference**, so no
credential value ever appears in this repository. What the capability does NOT do is create it.

Measured 2026-08-18: with the Secret absent, the claim is admitted, all seven resources compose
successfully, and then the initdb job fails forever with
`Error: secret "database-ok-robotics-app" not found` while the Cluster sits at
`phase: Setting up primary`. Nothing in the claim's own status says why — `operational` correctly
reports `Unknown/AwaitingCluster`, which is honest but not diagnostic.

Before the first claim for a cluster, provision the credential on **ok-mgmt**:

```bash
# basic-auth is the shape CNPG's initdb.secret expects; the password reaches kubectl on stdin,
# never in argv, and is never echoed.
openssl rand -base64 32 | tr -d '\n' > /dev/null   # (illustrative: see the real form below)
kubectl --kubeconfig <ok-mgmt> -n crossplane-system create secret generic database-ok-robotics-app \
  --type=kubernetes.io/basic-auth \
  --from-literal=username=app \
  --from-file=password=/dev/stdin <<<"$(openssl rand -base64 32 | tr -d '\n')"
```

**The right long-term answer is not a hand-created Secret.** ADR-Platform-025 established
Vault + Vault Secrets Operator as this platform's secret-sync mechanism; the app credential belongs
there, so that §11.4's rotation semantics have something to rotate. Until that is wired, a
hand-provisioned Secret is a documented prerequisite rather than a design.

Two smaller alternatives were considered and rejected for v1: omitting `initdb.secret` so CNPG
generates `<cluster>-app` itself (removes the prerequisite, but the consumer contract pins a known
Secret name, and the platform would no longer own the credential), and generating it inside the
Composition (which would place credential material in a composed resource).
