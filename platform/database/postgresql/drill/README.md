# PostgreSQL isolated restore drill

This directory holds the OK-145 workload-cluster spike/prototype required by
ADR-Platform-032 section 11.3. **Two fixed-backup drills have been executed** against ok-robotics:

| run | backup | reached | evidence | admissible? |
|---|---|---|---|---|
| 2026-08-17 | `20260817T104456` | timeline 2 / LSN `0/80001D0`, PT75S | `evidence/restoreverified-20260817t114640z.yaml` | **no** — pre-API |
| 2026-08-18 | `20260818T115641` | timeline 2 / LSN `0/6000120`, PT74S | `evidence/restoreverified-20260818t115710z.yaml` | **yes** — admitted by the ok-mgmt CRD (server dry run) |

The 2026-08-18 run targeted the `Database` composed by the Crossplane path
(`ok-robotics-7x6l2`, uid `a6b4b2ff-38f3-4cdf-ab2e-c7808d5e6326`) and binds that identity in
`spec.databaseRef`. Its five checks are derived from observed values, not written as constants.
**A composed Database starts empty**, so the semantic profile has nothing to read until a known
row exists: the probe row was seeded into `app` by hand and a fresh backup taken. An automated
verification cannot rely on that — see ADR-Platform-032 §13 bound 3.

The 2026-08-17 artifact remains historical point evidence for its named backup. It predates the
Database/XR UID binding now required by the RestoreVerified CRD and is not itself an admissible
instance of the final schema. The prototype does not schedule later drills, advance across
scheduled backups, publish evidence continuously, or operate a production recovery objective.
Its source path still uses the fixed `ok-robotics-evidence` Backup; continuous selection and
verification of later backups remains delivery work.

## Prerequisites — install in this order, each verified before the next

These were established by running it, and each one cost a failed attempt. Do not
skip the ordering or the namespace step.

| # | Component | Why, and the trap |
|---|---|---|
| 1 | cert-manager | Both the plugin and MinIO TLS need it. Verify by issuing a real `Certificate` and waiting for its condition — not by the install's exit code. |
| 2 | Barman Cloud Plugin **v0.14.0** | **Create `cnpg-system` first.** The release manifest does *not* create its own namespace, so every namespaced object fails `NotFound` while the CRD alone succeeds — which looks like a partial success. Its deployment is named **`barman-cloud`**, not `plugin-barman-cloud`. |
| 3 | CNPG 1.30.0 | Operator Ready. |
| 4 | MinIO over TLS | CA bundle must be Secret `minio-backup-store-ca` key `ca.crt` — the reviewed manifests reference those exact names. |
| 5 | Three MinIO identities | See below: the source **writer** is easy to forget and nothing works without it. |

**Three identities, not two.** Every barman-capable identity needs *unconditioned*
bucket-level `s3:ListBucket`: `barman-cloud` calls `HeadBucket`, S3 exposes no
separate action for it and accepts no `s3:prefix` condition, so a prefix-scoped
`ListBucket` yields `403 Forbidden` and no backup or restore can run. The
consequence is recorded in ADR §11.3: object *access* stays prefix-confined,
object *names* do not.

| identity | grants |
|---|---|
| `ok-db-backups-<cluster>-writer` | the database's own backups: write its prefix + bucket-level ListBucket |
| `ok-db-backups-<cluster>-reader` | the drill's read-only view of the protected source |
| `ok-db-drill-<run-id>-writer` | the recovery cluster's isolated WAL/backup destination |

The recovery identity has two separately provisioned MinIO users and two
Kubernetes Secrets. The source user's MinIO username is the source CNPG cluster
name and its policy permits only reads from
`ok-db-backups/${aws:username}/`. The destination user's MinIO username is the
run ID and its policy permits writes only to `ok-db-drill/${aws:username}/`.
The two supplied Secret names must differ. No credential value is accepted by
the runner, written to a temporary file, or rendered into a manifest.

For this OK-145 pass, the execution tuple is pinned to target/source
`ok-robotics`, namespace `database-ok-robotics`, the in-cluster MinIO service,
source Secret `ok-db-backups-ok-robotics-reader`, and per-run destination Secret
`ok-db-drill-<run-id>-writer`. The runner also verifies that the supplied
kubeconfig identifies `ok-robotics` before reading either Secret or applying.

`--source-cluster` is the only source identity input. The runner derives the
same value into `bootstrap.recovery.source`, `externalClusters[].name`, and the
Barman plugin `serverName`; the source `ObjectStore.destinationPath` remains
the bucket root `s3://ok-db-backups`. Consequently the effective server folder
is exactly `ok-db-backups/<source-cluster>/` and there is no independently
editable folder argument that can silently disagree with recovery bootstrap.
The recovered cluster archives new WAL through a second ObjectStore at
`s3://ok-db-drill/<run-id>`.

## Local validation

Run the deliberate failures before trusting the passing checks:

```bash
python3 tests/isolation-policy-check.py --negative-controls
python3 tests/render-recovery-cluster-check.py --negative-controls
python3 tests/isolation-policy-check.py
python3 tests/render-recovery-cluster-check.py
bash -n run-restore-drill.sh
python3 -c 'import ast, pathlib; [ast.parse(p.read_text(), filename=str(p)) for p in pathlib.Path("tests").glob("*.py")]'
python3 tests/minio-provisioning-check.py --negative-controls
python3 tests/minio-provisioning-check.py
python3 tests/restore-evidence-check.py --negative-controls
python3 tests/restore-evidence-check.py
```

Render for review without a kubeconfig:

```bash
bash run-restore-drill.sh --render-only \
  --source-cluster ok-robotics --run-id 20260817t120000z \
  --namespace database-ok-robotics \
  --minio-endpoint https://minio.minio.svc:9000 \
  --minio-ca-secret minio-backup-store-ca \
  --source-credentials-secret ok-db-backups-ok-robotics-reader \
  --drill-credentials-secret ok-db-drill-20260817t120000z-writer \
  --backup-id 20260817T020000 \
  --database-api-version platform.openkubes.ai/v1alpha1 \
  --database-kind Database \
  --database-name ok-robotics-render-development \
  --database-uid 81b14e99-9c0d-5952-91a3-b8a1528b4e28 \
  --postgres-image ghcr.io/cloudnative-pg/postgresql:18@sha256:<digest> \
  --storage-class local-path
```

Execution additionally requires `--execute --approve-isolated-restore` and a
readable `--kubeconfig`. The namespace and credential Secrets must already
exist. The runner refuses to overwrite a Cluster or ObjectStore, waits for the
recovery Cluster, runs heap-read and primary-key-index probes against the forcing-consumer
table, and removes the
scratch resources on exit unless `--retain` is explicit.

## Proof boundary

The local checks prove only the authored policy shape, disjoint prefixes,
single-input source-name derivation, distinct Secret references, and absence of
credential values in rendered YAML. They do **not** prove that MinIO enforces
the policies, that the named source contains a usable base backup and complete
WAL, that CNPG and the Barman plugin admit these manifests, that recovery
finishes, or that application data is semantically correct. Only an attended
workload-cluster run can supply that acceptance evidence. Even a successful run
proves only the explicitly recorded checks for that backup, target environment,
image, and time; catalogue counts are not a structural-integrity claim. It does
not prove application-semantic consistency or a general RPO, RTO, or production
restore guarantee.

Runner cleanup is limited to per-run recovery resources and the per-run writer identity (unless
`--retain` is selected). It does not delete the source CNPG Cluster, source PVC, source
ObjectStore, fixed Backup, MinIO installation, operators, or namespaces. Those persistent
resources are outside routine drill teardown; destroying the fixed backup would orphan the
historical evidence reference.
