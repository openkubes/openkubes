# 03 — Upgrade 1.23 → 1.24 under load, rollback

- Test IDs: U1, U2, U3
- Date (UTC): 2026-10-30T14:26Z – 2026-10-31T09:33Z (three runs; the measured run 3: 2026-10-31T09:25:45Z – 09:32:24Z)
- Commit: `48dba85` plus the Phase 4 changes in this commit
- Environment: VM `ok-knative-local`, K3s `v1.35.5+k3s1`. From Serving and net-kourier `knative-v1.23.0` and Eventing `knative-v1.23.1` to `knative-v1.24.0` for all three. See [02-knative-install.md](02-knative-install.md)

## Summary

Run 3 upgraded every component to `1.24.0`:

- **0 HTTP errors** in 476 requests during the 99 s upgrade window, and 0 errors in 1388 requests during the 5 min after-run.
- U2 lost no event that had been accepted with `202`, saw no duplicates and nothing out of order.
- One send in 390 got `connection refused`, during the `mt-broker-ingress` pod swap.

It took **three attempts**. The release manifests cannot be re-applied server-side, as B8 prescribes, without changes.

- Three fields in the release YAMLs are owned at runtime by a controller.
- Each one makes server-side apply fail with a conflict.
- They were resolved by three narrow, checked derivation rules (CP3 decisions B, B2 and B3), not by `--force-conflicts`.

## Steps

```bash
make -C architecture/spikes/OK-211-knative-serverless apps-upgrade          # ksvc podinfo-upgrade (min-scale 1) + u1-probe (curl every 200 ms)
make -C … apps-upgrade-events                                                # ok211-events: broker default, event-display Deployment, trigger, PingSource, u2-sender (1 event/s)
make -C … knative-dry-run TO=1.24                                            # new: server-side dry run of every file the upgrade sends
make -C … knative-upgrade TO=1.24                                            # marks in evidence/raw/upgrade-steps.log
make -C … knative-verify                                                     # all components on 1.24, overrides, gateway digest
make -C … upgrade-collect                                                    # after 5 min after-run: pod logs + evaluation -> measurements.json
make -C … apps-upgrade-down                                                  # podinfo-upgrade, u1-probe and ok211-events removed (B9: delete podinfo-upgrade)
```

Upgrade order in `scripts/knative.sh upgrade_line`:

1. `serving-crds`, `eventing-crds`, wait Established.
2. `serving-core`, wait rollout of `webhook`, `controller`, `activator`, `autoscaler` to the new version label.
3. `kourier`, wait rollout of `net-kourier-controller` and the gateway.
4. Overrides re-applied (merge patches).
5. `eventing-core`, wait rollout of `eventing-webhook` and `eventing-controller`.
6. `in-memory-channel`, `mt-channel-broker`.
7. Wait until every deployment in the three namespaces has rolled out. This is the end of the window.
8. Post-install Jobs.

The [Knative kubectl upgrade guide](https://knative.dev/docs/install/upgrade/upgrade-installation/) uses client-side `kubectl apply` and gives no finer order. The order above follows B9 U1.

## Observed

### Three runs

| Run | Start | Outcome | Evidence |
|---|---|---|---|
| 1 | 2026-10-30T14:28:55Z | Both CRD files applied. `serving-core.yaml` was rejected with 2 SSA conflicts (see below). 57 objects were applied, so `activator`, `autoscaler`, `controller` and `webhook` ran `1.24.0`, while Kourier stayed on `1.23.0` and Eventing on `1.23.1`. Stopped at CP3 without forcing. U1 kept running in the mixed state until 2026-10-31T08:43Z: **0 errors in 52 780 requests**. | [raw/upgrade-attempt1-*](raw/) |
| 2 | 2026-10-31T08:57:41Z (after a snapshot restore, rule B) | Serving and Kourier on `1.24.0` in 31 s. `eventing-core.yaml` was rejected (rules B2/B3 not yet in place). U1 had 0 errors in 3989 requests. Stopped at CP3. | [raw/upgrade-attempt2-*](raw/) |
| 3 | 2026-10-31T09:25:45Z (after a snapshot restore, rules B+B2+B3, dry run green) | **Complete**, measured below | [raw/upgrade-steps.log](raw/upgrade-steps.log) |

### Server-side apply conflicts (finding)

Every conflict has the same cause. The release YAML sets a field that a controller owns at runtime:

- The controller writes it with an `Update`, and server-side apply then records the controller as the field's manager.
- A later apply by `knative-release` with the release value conflicts with that manager.
- The first install did not conflict, because the controllers had not written those fields yet.

| # | Object(s) | Field | Runtime manager | Upstream manifest says | Rule (CP3) |
|---|---|---|---|---|---|
| 1 | `MutatingWebhookConfiguration webhook.serving.knative.dev`, `ValidatingWebhookConfiguration validation.webhook.serving.knative.dev` (serving-core) | `.webhooks[].rules` | `webhook` (Update) | Ships static rules (length 1). The other 7 webhook configurations (4 in eventing-core, 2 in in-memory-channel, `config.webhook.serving.knative.dev`) ship **without** rules. | B |
| 2 | ClusterRoles `addressable-resolver`, `channelable-manipulator`, `crossnamespace-subscriber`, `podspecable-binding`, `source-observer` (eventing-core, all with `aggregationRule`) | `.rules` | `clusterrole-aggregation-controller` | `rules: [] # Rules are automatically filled in by the controller manager.` Serving ships its aggregated ClusterRoles without `rules`. | B2 |
| 3 | Deployment `knative-eventing/pingsource-mt-adapter` | `.spec.replicas`, the values of `K_OBSERVABILITY_CONFIG`, `K_LOGGING_CONFIG`, `K_LEADER_ELECTION_CONFIG`, `K_NO_SHUTDOWN_AFTER` | `controller` (eventing-controller, Update) | `replicas: 0` with the comment "when set to 0 (and only 0) will be set to 1 when the first PingSource is created", and "DO NOT MODIFY: The values below are being filled by the ping source controller" | B3 |

Conflict #3 shows that `--force-conflicts` is not harmless in general. Forcing the release value would set the adapter to 0 replicas, so every PingSource would stop until the controller reconciled the Deployment again.

**How the rules are implemented** (`scripts/knative.sh derive_apply_set`):

- The pinned file is checked against its SHA-256 first, as before.
- A derived copy in `.local/manifests/<line>/derived/` drops exactly these fields.
- A second, independent jq implementation of the same rules must produce the same objects. Otherwise the apply aborts.
- An offline negative test (a derived file with an extra change) was rejected.
- Files where no rule removes anything are applied unchanged. This holds for CRDs, `kourier.yaml`, `in-memory-channel.yaml` and `mt-channel-broker.yaml`.
- The derived SHA-256 is written to `upgrade-steps.log`:
  - `1.24/serving-core.yaml` → `52afa88e4374cf88fc43d85725218bd0d1451ae2a882455dfdc467cb9ad3bc32`
  - `1.24/eventing-core.yaml` → `d4fe18623575bbb75bfcb1c6146da58143573b8ef76451f02a8d62e957047282`

After run 3 the controllers had refilled every removed field:

- 10 rules in each Serving webhook configuration.
- 10/2/3/3/1 rules in the five aggregated ClusterRoles.
- `pingsource-mt-adapter` with 1/1 replicas and the controller-filled env values set.

The same three places would need `ignoreDifferences` (or `RespectIgnoreDifferences`) in Argo CD for G1.

**Dry run before applying:** `make knative-dry-run TO=1.24` sends each file exactly as the upgrade would, with `--dry-run=server`:

- the derived release files via server-side apply;
- the non-Job objects of the post-install files via apply;
- the Jobs via `create`.

It found the third conflict and two script defects (next section) before run 3. In run 3 it was green on the freshly restored 1.23 cluster ([raw/upgrade-run3-dry-run-1.24-from-1.23.log](raw/upgrade-run3-dry-run-1.24-from-1.23.log)), and green again under load after the PingSource controller had taken ownership of the adapter ([raw/upgrade-run3-dry-run-1.24-under-load.log](raw/upgrade-run3-dry-run-1.24-under-load.log)).

### Script defects found on the way (fixed before run 3)

1. `run_jobs` extracted the non-Job objects with `yq -N`, which drops the `---` separators. ClusterRole, ServiceAccount and ClusterRoleBinding of `eventing-post-install.yaml` were merged into one object, and the server rejected it: ".rules: field not declared in schema".
2. `run_jobs` counted and indexed Jobs per YAML document instead of across the file. It now uses `yq ea`: 2 Jobs in Serving, 1 in Eventing.
3. The first version of `knative-dry-run` matched only "conflict with". kubectl writes "conflicts with" plus a field list when several fields of one object conflict, so conflict #3 was hidden. It now prints every error line and the field list. I had reported "no further conflicts" at CP3 based on that incomplete output, and corrected it at the next CP3.

### Run 3 — step timeline ([raw/upgrade-steps.log](raw/upgrade-steps.log))

| Step | UTC | Duration |
|---|---|---|
| Apply `serving-crds`, `eventing-crds`, wait Established, derive `serving-core` | 09:25:45 → 09:25:51 | 6 s |
| Apply `serving-core` | 09:25:51 | < 1 s |
| Rollout `webhook` / `controller` / `activator` / `autoscaler` → 1.24.0 | 09:25:51 → 09:26:09 | 13 s / 3 s / 2 s / < 1 s |
| Apply `kourier`, rollout `net-kourier-controller`, gateway | 09:26:09 → 09:26:17 | 8 s |
| Overrides `config-network`, `config-domain` | 09:26:17 | < 1 s |
| Apply `eventing-core`, rollout `eventing-webhook` / `eventing-controller` | 09:26:17 → 09:26:47 | 1 s + 11 s + 18 s |
| Apply `in-memory-channel`, `mt-channel-broker` | 09:26:47 | < 1 s |
| Wait until all deployments are rolled out (image pulls, e.g. `mt-broker-ingress` 14.6 s) | 09:26:47 → 09:27:24 | 37 s |
| **Upgrade window** (first CRD apply → all Available) | 09:25:45 → 09:27:24 | **99 s** |
| Post-install: `storage-version-migration-serving`, `cleanup-serving`, `storage-version-migration-eventing` Complete | 09:27:24 → 09:27:52 | 9 s + 9 s + 10 s |
| Total | 09:25:45 → 09:27:52 | 127 s |

After the upgrade: `make knative-verify` all PASS. 15 deployments and the `request-reply` StatefulSet carry `app.kubernetes.io/version=1.24.0`, all 1/1 ([raw/knative-1.24-versions.tsv](raw/knative-1.24-versions.tsv)). Images and resources: [raw/knative-1.24-components.json](raw/knative-1.24-components.json). `config-network` and `config-domain` are unchanged.

The Kourier gateway still runs `envoy:v1.37-latest`, `imageID` `sha256:7765ad61…72a4`, the expected digest. The tag in the 1.24 manifest is the same floating tag as in 1.23, so the digest pin from CP1 decision (a) keeps mattering.

### U1 — HTTP during the upgrade (run 3)

Probe: `u1-probe` (curl image by digest), `curl -sS -o /dev/null --max-time 5` every 200 ms against `kourier.kourier-system.svc.cluster.local`, `Host: podinfo-upgrade.ok211-serving.ok211.internal`. ksvc `podinfo-upgrade` with `min-scale: "1"`. Times from `kubectl logs --timestamps`. Raw: [raw/u1-probe-20261031T093245Z.log](raw/u1-probe-20261031T093245Z.log). JSON: `U1` in [raw/measurements.json](raw/measurements.json).

| Period | Requests | Errors (HTTP ≠ 200 or curl exit ≠ 0) | Error rate | Latency p50 / p90 / p99 / max |
|---|---|---|---|---|
| Before the window (≈ 1.5 min) | 468 | 0 | 0 % | — |
| **Upgrade window, 99 s** | **476** | **0** | **0 %** | 1.5 / 2.6 / 4.7 / **7.2 ms** |
| After-run, 300 s | 1388 | 0 | 0 % | — |

The slowest request (7.2 ms) fell into the `mt-channel-broker` apply, while Eventing pods were starting. Neither the swap of `activator`, `net-kourier-controller` or the gateway, nor the swap of the `webhook`, produced an error. Since `min-scale: 1` keeps the revision pod, the activator is not in the request path. The test does not cover a revision that is scaled to zero during the upgrade.

### U2 — events during the upgrade (run 3)

Sender `u2-sender`: one CloudEvent per second with `Ce-Seq` to the broker ingress, `Ce-Type: dev.openkubes.ok211.upgrade`. Receiver: `event-display` Deployment behind trigger `u2-all`. Broker: MTChannelBasedBroker/InMemoryChannel, delivery from `config-br-defaults`: retry 10, exponential, `PT0.2S`. Raw: [raw/u2-sender-20261031T093245Z.log](raw/u2-sender-20261031T093245Z.log), [raw/u2-received-20261031T093245Z.tsv](raw/u2-received-20261031T093245Z.tsv). JSON: `U2` in [raw/measurements.json](raw/measurements.json). Period: window plus after-run, 09:25:45Z – 09:32:24Z.

| Metric | Value |
|---|---|
| Sent | 390 |
| Accepted (`202`) | 389 |
| Rejected | **1**: seq 169 at 09:27:04.457Z, curl exit 7 (`connection refused`), during step "apply 1.24/mt-channel-broker.yaml" |
| Delivered (unique, of the accepted) | 389 |
| Lost after `202` | **0** |
| Duplicates | **0** |
| Out of order | 0 |
| PingSource cycles in the window | 2 of 2 expected (09:26:00.3Z, 09:27:00.4Z); 8 received in total |

Cause of the one rejection, from events and pod status:

- The new `mt-broker-ingress` pod became Ready at 09:27:04Z.
- In the same second the old ReplicaSet was scaled to 0 and its pod got "Stopping container ingress".
- The single-replica broker ingress has a gap of about one second during the swap. A producer without its own retry sees an error.
- The retry policy of the broker does not help here, because it applies only after ingress has accepted the event.

At the start of each of the three runs, the first one or two sends after the broker was created failed: `500` and a timeout in run 3, a timeout in run 2, `500` and a timeout in run 1. This is broker warm-up, not part of the upgrade window.

### U3 — rollback

**What the Knative documentation says** (read 2026-10-31):

- [Upgrading Knative](https://knative.dev/docs/install/upgrade/): "Knative supports upgrading by a single minor version number."
- [Upgrading with kubectl](https://knative.dev/docs/install/upgrade/upgrade-installation/), the path this spike uses (YAML install): no statement about downgrade or rollback.
- [Upgrading with the Knative Operator](https://knative.dev/docs/install/upgrade/upgrade-installation-with-operator/), section "Rollback to an earlier version": "If the upgrade fails, you can rollback to restore your Knative to the previous version." It does this by setting `spec.version` in the KnativeServing/KnativeEventing CR.

So a documented rollback exists only for the Operator, not for YAML installs. No YAML downgrade was attempted, as B9 requires.

**Environment rollback, practical.** `make down` → `make vm-restore NAME=knative-1-23` → `make vm-start tunnel`, using the qemu snapshot from Phase 3. It was done twice, before run 2 and before run 3:

| Restore | Stop | Restore | Start + tunnel | First `knative-verify` PASS | First smoke `200` |
|---|---|---|---|---|---|
| Before run 2 | 08:47:06 → 08:48:40 (94 s) | 1 s | 08:48:41 → 08:48:57 | 08:49:42 | 08:50:25 (3 × `503` before) |
| Before run 3 | → 09:22:09 | 1 s | 09:22:10 → 09:22:24 | 09:22:30 | 09:23:47 (`000`, 4 × `503` before) |

What it covers and what it does not:

- It returns the whole node, including etcd state, every workload and every CR, to the snapshot time. Anything created after the snapshot is lost.
- It is an environment rollback for a single-node lab. It is not a Knative rollback for a cluster that carries other workloads.
- The `503` window after every restart repeats the P3-restart finding (stale SKS endpoints after a restart): 43 s and 77 s after `knative-verify` was green.

## Verdict

| ID | Verdict | Key value | Note |
|---|---|---|---|
| U1 | PASS | 0 errors in 476 requests in the 99 s window (0 %); max latency 7.2 ms; after-run 0 in 1388 | Measured series complete, raw values in `measurements.json` |
| U2 | PASS | 389/389 accepted events delivered, 0 duplicates, 0 out of order; 2/2 PingSource cycles; 1 of 390 sends refused during the broker-ingress swap | Finding: producers need their own retry during ingress rollouts |
| U3 | PASS | YAML path: no documented downgrade; Operator: "Rollback to an earlier version"; snapshot restore done twice, ≈ 2 min to a running VM | No YAML downgrade attempted |
| P4-ssa-conflicts | FINDING | 3 classes of runtime-owned fields; resolved with derivation rules B, B2, B3 and no `--force-conflicts` | Input for M3 and G1 |
| P4-all-1.24 | PASS | 16/16 workloads on `1.24.0`, `knative-verify` PASS, overrides intact | — |

Input for M3 (assessed in Phase 10):

- The upgrade is declarative: manifests plus the documented post-install Jobs, with no manual edit of any resource.
- U1 had no errors after the upgrade, and an error rate of 0 % ≤ 1 % during it.
- It needed three derivation rules on the release manifests for server-side apply. B8 requires server-side apply. The [Knative guide](https://knative.dev/docs/install/upgrade/upgrade-installation/) uses client-side apply.

## What this proves / What this does not prove

| Proves | Does not prove |
|---|---|
| A 1.23 → 1.24 minor upgrade of Serving, Kourier and Eventing on single-node K3s keeps a `min-scale: 1` service fully available (0/476 errors) | Behaviour for a scaled-to-zero service, a cold start during the upgrade, or a multi-node cluster with more replicas |
| Server-side apply of the unmodified release YAMLs fails on re-apply, and three narrow derivation rules make it work without forcing | That the three rules are complete for later versions. `knative-dry-run` must be run before each upgrade. |
| No accepted event was lost or duplicated with the in-memory channel during the upgrade | Durability across a dispatcher crash (InMemoryChannel keeps nothing on restart), or behaviour with Kafka/NATS channels |
| The single-replica broker ingress refuses connections for about 1 s during its rollout | How often that happens in production, or whether a second replica or PDB removes it |
| Snapshot restore of the VM is a fast environment rollback (≈ 2 min) | A Knative-level rollback on a shared cluster. For YAML installs there is no documented one. |

## Deviations from BRIEF

1. **Release manifests are not applied byte-for-byte unchanged.** Three derivation rules (CP3 decisions B, B2, B3 by the human on 2026-10-31) remove runtime-owned fields before the server-side apply. The pinned file is still verified first, and the derived file is checked against an independent implementation and logged with its SHA-256. `--force-conflicts` was never used.
2. **Three runs instead of one.** Runs 1 and 2 stopped at a conflict, and their raw data is kept. Each later run started from the `knative-1-23` snapshot, so run 3 measures an uninterrupted upgrade.
3. New target `knative-dry-run TO=<line>`, not listed in B9. It changes nothing on the cluster.
4. New target `apps-upgrade-down`. It removes `podinfo-upgrade` (B9 U1) and also `u1-probe` and the namespace `ok211-events` with all U2 objects, so the U2 load does not affect Phase 5 measurements.
5. Run 1's U1 probe kept running for about 18 h in the mixed state while the decision was pending. The Mac slept during that time, so the effective request rate is lower than 5/s (52 780 requests). The data is kept as a side observation, not as a U1 result.
6. Running U1 and U2 at the same time is not specified in B9. They ran together in all three runs.
