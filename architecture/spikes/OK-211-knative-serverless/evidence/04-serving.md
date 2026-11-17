# 04 — Serving PoC

- Test IDs: S1–S10
- Date (UTC): 2026-10-31T09:39Z – 10:14Z
- Commit: `f17a74e` plus the Phase 5 changes in this commit
- Environment: VM `ok-knative-local`, K3s `v1.35.5+k3s1`, Knative Serving, net-kourier and Eventing `1.24.0` after the upgrade in [03-upgrade.md](03-upgrade.md). Single node with 4 vCPUs and 8 GiB.

All series ran inside the cluster (B11):

- curl in `ok211-probe`, or fortio `1.76.0` as a Job in `ok211-load` (PSA `restricted`, non-root).
- Target: `http://kourier.kourier-system.svc.cluster.local` with `Host: <ksvc>.ok211-serving.ok211.internal`.

Each series has a JSON line in [raw/measurements.json](raw/measurements.json) with the configuration, the raw values and the stats. Percentiles are nearest-rank. For n < 10 only min, median and max are given. S5 and S6 percentiles are fortio's histogram values.

**Configuration** (identical for every series, recorded per series):

- No override in `config-autoscaler` or `config-defaults`, so the release defaults apply:
  - `stable-window` 60s, `scale-to-zero-grace-period` 30s, `scale-to-zero-pod-retention-period` 0s
  - `container-concurrency-target-percentage` 70, `container-concurrency-target-default` 100
  - `panic-window-percentage` 10, `panic-threshold-percentage` 200
  - `revision-timeout-seconds` 300, `max-revision-timeout-seconds` 600
- Image `podinfo` `6.16.0` by digest (`6.17.0` for the second S8 revision).
- Annotations per service:

| Service | Used in | Annotations / spec |
|---|---|---|
| `podinfo` rev `00001` | S1, S2 | none (defaults) |
| `podinfo` rev `00002` | S3, S4, S5 | `autoscaling.knative.dev/window: 6s` (B11 "beschleunigtes Herunterskalieren"; grace period stays global) |
| `podinfo-scale` | S6 | `autoscaling.knative.dev/target: "10"` |
| `podinfo-min1` | S7, S10 | `autoscaling.knative.dev/min-scale: "1"` |
| `podinfo-split` | S8 | named revisions `podinfo-split-v6160` / `-v6170`, readiness `successThreshold: 1` (see S8) |
| `podinfo-timeout` | S9 | `timeoutSeconds: 20` |

**Disturbances:**

- The Mac also ran this session.
- No other Multipass instance existed, and Docker Desktop was not running (see [00-preflight.md](00-preflight.md)).
- The load average for each S10 sample is in its raw file.

## Steps

```bash
make -C architecture/spikes/OK-211-knative-serverless measure-s1
make -C … measure-scale-to-zero                       # S2, RUNS=3, defaults
make -C … apps-serving-fastdown                       # podinfo rev 00002 with window 6s
make -C … measure-coldstart ID=S3 KSVC=podinfo N=10
make -C … measure-coldstart ID=S4 KSVC=podinfo N=3    # before each run: scripts/node-image.sh rmi <digest> (sudo k3s crictl rmi via ok211::vm_ssh)
make -C … measure-latency                             # S5
make -C … apps-serving-exp                            # podinfo-scale, podinfo-min1 (after S4: min1 pins the 6.16.0 image)
make -C … measure-autoscale                           # S6
make -C … measure-coldstart ID=S7 KSVC=podinfo-min1 N=10
make -C … exp-s8
make -C … exp-s9
make -C … measure-overhead                            # S10
make -C … apps-serving-down                           # experiment services removed, podinfo stays
```

Before every cold-start run, `measure-serving.sh wait_zero` checks the B11 state, then waits 10 s:

- no pod of the revision, not even `Terminating`;
- PodAutoscaler `actualScale` 0;
- SKS mode `Proxy`.

## Observed

### S1 — objects ([raw/s1-objects-20261031T093929Z.txt](raw/s1-objects-20261031T093929Z.txt))

`ksvc/podinfo` creates this owner chain:

- `Configuration/podinfo` ← Service
- `Revision/podinfo-00001` ← Configuration
- `Route/podinfo` ← Service
- `PodAutoscaler/podinfo-00001` ← Revision
- `ServerlessService/podinfo-00001` ← PodAutoscaler (mode `Proxy`, `numActivators` 3)
- `ingresses.networking.internal.knative.dev/podinfo` ← Route

The first request after the upgrade, from 0 pods, returned `200` in 1.82 s.

### S2 — scale-to-zero with defaults ([raw/s2-scale-to-zero-20261031T093942Z.tsv](raw/s2-scale-to-zero-20261031T093942Z.tsv))

20 requests, then the clock starts after the last one. The Mac polls every 1 s; the Mac–VM clock skew was ≈ 0.2 s.

| Run | PodAutoscaler `desiredScale` 0 after | Pod deletion requested after¹ | No pod left after |
|---|---|---|---|
| 1 | 62.5 s | 62 s | 97.1 s |
| 2 | 62.3 s | 61 s | 95.2 s |
| 3 | 61.1 s | 61 s | 93.9 s |
| **min / median / max** | **61.1 / 62.3 / 62.5 s** | 61 / 61 / 62 s | **93.9 / 95.2 / 97.1 s** |

¹ The pod's `deletionTimestamp` minus the last request, both with 1 s resolution, **minus the 300 s grace period**. The raw values 361–362 s include `terminationGracePeriodSeconds: 300` (= `revision-timeout-seconds`).

Compared with the configuration:

- `desiredScale` reaches 0 one to two seconds after `stable-window` (60s), because the window must have seen no traffic.
- After that the activator is put back in the path. `scale-to-zero-grace-period` 30s is an upper bound for that handover, not a fixed wait.
- `scale-to-zero-pod-retention-period` 0s adds nothing.
- The pod then needs another ≈ 33 s to disappear. The user container's `preStop` calls the queue-proxy `/wait-for-drain`, and the queue-proxy drains before the pod ends.

So, with defaults, an idle service holds its pod for **≈ 95 s**.

### S3 — cold start, image cached (podinfo rev 00002, [raw/s3-coldstart-20261031T094531Z.tsv](raw/s3-coldstart-20261031T094531Z.tsv))

| n | min | median | p90 | max | errors |
|---|---|---|---|---|---|
| 10 | **1028 ms** | **1347 ms** | **1981 ms** | **2108 ms** | 0 |

The Pulled event read "Container image … already present on machine" in all 10 runs.

Coarse breakdown from the pod timestamps, relative to the request start, all with 1 s resolution:

| Event | Offset in all 10 runs |
|---|---|
| Pod created | 0–1 s |
| Scheduled | 0–1 s |
| User container and queue-proxy started | 1–2 s |
| Ready | 1–2 s |

The response followed within the same second. On a single node with a cached image, the cold start is dominated by container start and the first readiness probe, not by scheduling.

### S4 — cold start, image not cached ([raw/s4-coldstart-20261031T095551Z.tsv](raw/s4-coldstart-20261031T095551Z.tsv))

Before each run, `node-image.sh rmi` removed `ghcr.io/stefanprodan/podinfo@sha256:2c88592f…6d4d` from the node:

- it checked first that no pod in any namespace used the digest;
- afterwards `crictl images --digests` no longer listed it.

The `queue-proxy` image stayed cached, as B9 notes.

| Run | Total | Pull (event `Pulled`) | Pull share | Containers started (coarse) |
|---|---|---|---|---|
| 1 | 7209 ms | 5686 ms | 79 % | +6 s |
| 2 | 7936 ms | 5823 ms | 73 % | +7 s |
| 3 | 9061 ms | 6812 ms | 75 % | +8 s |
| **min / median / max** | **7209 / 7936 / 9061 ms** | 5686 / 5823 / 6812 ms | 73–79 % | — |

The image is 33 586 887 bytes, so the pull rate was ≈ 5–6 MB/s over the Mac's link. The pull dominates the cold start once the image is not on the node. Estimates for large AI images belong in the report, marked "estimate".

Run 3's "ready" offset in the measurements JSON is `0`. The first script version took the `lastTransitionTime` of the Ready condition regardless of its status. That value is not reliable; container start (+8 s) and total (9.06 s) are. The extraction now requires `status == "True"`; S7 already used it.

### S5 — warm latency ([raw/s5-fortio-20261031T100030Z.json](raw/s5-fortio-20261031T100030Z.json))

fortio, 10 qps, 1 connection, 200 requests, after a 30 s warm-up that is not evaluated. podinfo rev 00002 was warm.

| count | codes | min | p50 | p90 | p99 | max |
|---|---|---|---|---|---|---|
| 200 | 200 × `200` | 0.79 ms | **1.89 ms** | **2.99 ms** | **5.0 ms** | 6.64 ms |

### S6 — autoscaling ([raw/s6-pods-20261031T100105Z.tsv](raw/s6-pods-20261031T100105Z.tsv), [raw/s6-fortio-20261031T100105Z.json](raw/s6-fortio-20261031T100105Z.json), [raw/s6-autoscaler-20261031T100105Z.log](raw/s6-autoscaler-20261031T100105Z.log))

Setup:

- `podinfo-scale` with target 10, which gives an effective target of 7 concurrent requests per pod at 70 %.
- It started from 0 pods (B11 state); there was no warm-up, so the scale-up from zero is part of the series.
- fortio ran with 50 connections and no rate limit for 60 s, from 10:02:50.1Z to 10:03:50.1Z.
- Samples were taken every 2.3 s on average (max 4 s), 69 in total.

| Metric | Value |
|---|---|
| Requests / codes | 1 112 313, all `200`, 18 538 req/s |
| Latency p50 / p99 / max | 2.08 / 11.96 / 60.7 ms |
| Desired ≥ 5 | t = 4 s |
| **Max pods** | **6** (desired 6), first reached at t = 9 s, held until the load ended |
| Panic mode | **yes**: "PANICKING." at 10:02:51.1Z (1 s after the start), "Un-panicking." at 10:03:51.1Z (1 s after the end, one stable window) |
| After the load | desired dropped below 6 at t = 69 s (≈ 7 s after the end), desired 0 at t = 123 s (≈ 61 s after the end), last pod gone at t = 156 s |

The arithmetic estimate was 50 / 7 ≈ 7.1, so about 8 pods. **6** were observed. Not verified: on one node with 4 vCPUs, part of the 50 in-flight requests sits in fortio and Envoy rather than in the pods, so the concurrency the autoscaler sees per pod is lower. The autoscaler log contains no per-tick concurrency value that would settle this. Scale-down follows the stable window, as in S2.

### S7 — min-scale 1 ([raw/s7-coldstart-20261031T100558Z.tsv](raw/s7-coldstart-20261031T100558Z.tsv))

| n | min | median | p90 | max | errors |
|---|---|---|---|---|---|
| 10 | 1 ms | **2 ms** | 3 ms | 26 ms | 0 |

All 10 requests went to the same pod, which had been Ready 295–300 s before. There was no cold start. The price is one pod running all the time: 1m CPU and 14 Mi for the user container plus 1m and 6 Mi for the queue-proxy at idle (S10), and a scheduling reservation of 25m CPU for the queue-proxy.

### S8 — revisions, traffic split, rollback ([raw/s8-split-20261031T100723Z.txt](raw/s8-split-20261031T100723Z.txt))

| Step | Result |
|---|---|
| 1 → 2: new revision `podinfo-split-v6170` (6.17.0), traffic 80/20, tag `candidate` | Traffic status as declared; tag URL `http://candidate-podinfo-split.ok211-serving.ok211.internal` |
| 200 requests, after 20 warm-up requests | **156 × 6.16.0, 44 × 6.17.0 (78/22)** |
| 20 requests to the tag host | **20 × 6.17.0** |
| 3: rollback, 100 % to `v6160` (only `traffic` changes) | 200 × 6.16.0, tag host still 20 × 6.17.0 |
| Revisions before / after the rollback | `v6160`, `v6170` / unchanged: **no new deploy** |

**Finding (relevant for G1 and GitOps):**

- The first run of step 3 was rejected by the webhook: "Saw the following changes without a name change (-old +new): spec.template.metadata.name … ReadinessProbe.SuccessThreshold: - "1" + "0"". The partial output is in [raw/s8-split-20261031T100609Z.txt](raw/s8-split-20261031T100609Z.txt).
- So re-applying the unchanged, named template with server-side apply fails, because the stored spec carries the Knative default `successThreshold: 1` and the applied one does not.
- `managedFields` attribute that field to no manager, so the mechanism is **not identified**.
- `make lint-server` (server-side dry run) reproduces the failure with the original manifest and passes once `successThreshold: 1` is written into the manifest.
- The S8 manifests now state it. A GitOps tool that re-applies named revisions needs the same, or must exclude the field from its diff.

### S9 — request timeout ([raw/s9-timeout-20261031T100737Z.txt](raw/s9-timeout-20261031T100737Z.txt))

`podinfo-timeout` with `timeoutSeconds: 20`, warm.

| Request | Result |
|---|---|
| `/delay/10` | `200` after 10.04 s |
| `/delay/30` | **`504` after 20.00 s**; queue-proxy logs `WARNING … "Request timeout: 20s"` |

The `config-defaults` release values are:

| Key | Value |
|---|---|
| `revision-timeout-seconds` | 300 |
| `max-revision-timeout-seconds` | 600 |
| `revision-response-start-timeout-seconds` | 300 |
| `revision-idle-timeout-seconds` | 0 (infinite) |

Without an override, a request can therefore last at most 600 s (10 min). That is the basis for Scope 5. I did not test that a `timeoutSeconds` above 600 is rejected.

### S10 — resource overhead without load ([raw/resources-s10-knative-1.24-20261031T101139Z.txt](raw/resources-s10-knative-1.24-20261031T101139Z.txt), [raw/s10-queue-proxy-20261031T101341Z.txt](raw/s10-queue-proxy-20261031T101341Z.txt))

`kubectl top` (metrics-server), 3 samples 60 s apart; requests and limits from the pod specs. Only `podinfo-min1` had a running pod.

| Scope | CPU mean / max | Memory mean / max | Requests CPU / memory | Limits CPU / memory |
|---|---|---|---|---|
| `knative-serving` | 9m / 10m | 86 / 89 Mi | 800m / 560 Mi | 4500m / 3600 Mi |
| `kourier-system` | 4m / 4m | 73 / 73 Mi | 200m / 200 Mi | 1000m / 800 Mi |
| `knative-eventing` | 19m / 20m | 132 / 132 Mi | 750m / 578 Mi | 2200m / 4296 Mi |
| **Knative total** | **32m** | **291 Mi** | **1750m / 1338 Mi** | — |
| `kube-system` | 9m | 185 Mi | 200m / 140 Mi | — / 170 Mi |
| Node | 125m / 134m | 2397 / 2410 Mi | — | — |
| Node, baseline (Phase 2, empty cluster) | 60m / 73m | 638 / 645 Mi | — | — |

Per service, the queue-proxy of `podinfo-min1` used **1m CPU and 6 Mi**. Its spec requests 25m CPU and sets no memory request and no limits. The user container used 1m and 14 Mi.

Reading it:

- Knative's own pods use little at idle: 32m and 291 Mi.
- But they **reserve 1750m CPU on a 4-CPU node**, 44 %. Requests decide schedulability, so this is the cost that matters for small clusters.
- The node's memory rose by 1759 Mi compared with the baseline, while all pods together account for 505 Mi. Not verified: the rest is node-level usage outside pods, such as the containerd image store and page cache after the image pulls of this session.
- Eventing's requests rose from 625m (1.23, Phase 3) to 750m. The difference is `pingsource-mt-adapter` (125m). It ran with 0 replicas until the U2 PingSource existed, and its controller does not scale it back to 0 after the PingSource was deleted.

## Verdict

| ID | Verdict | Key value | Note |
|---|---|---|---|
| S1 | PASS | Ready; 6 objects with owner chain; `200` | — |
| S2 | PASS | desired 0 after 61–62 s, pod gone after 94–97 s (n = 3) | matches stable-window 60s + drain |
| S3 | PASS | cold start median 1347 ms, p90 1981 ms (n = 10), 0 errors | image cached |
| S4 | PASS | 7.2 / 7.9 / 9.1 s, pull 73–79 % | queue-proxy cached |
| S5 | PASS | p50 1.89 ms, p90 2.99 ms, p99 5.0 ms | — |
| S6 | PASS | max 6 pods after 9 s, panic yes, 0 errors in 1.1 M requests, back to 0 | 6 instead of ≈ 8 (not explained) |
| S7 | PASS | no cold start, median 2 ms | — |
| S8 | PASS | 78/22, tag only 6.17.0, rollback without a new revision | Finding: named template + SSA needs `successThreshold: 1` |
| S9 | PASS | `504` after 20.0 s; defaults 300 / 600 s | — |
| S10 | PASS | Knative 32m / 291 Mi used, 1750m / 1338 Mi requested; queue-proxy 1m / 6 Mi | — |

## What this proves / What this does not prove

| Proves | Does not prove |
|---|---|
| Scale-to-zero works with defaults and takes ≈ 95 s until the pod is gone | Behaviour with `scale-down-delay`, `scale-to-zero-pod-retention-period` > 0, or other grace periods |
| On one node with a cached 34 MB image, a cold start takes 1.0–2.1 s; uncached, the pull dominates (73–79 %) | Cold starts on multi-node clusters, with registry mirrors, or with large (GB) images. Those are estimates for the report only. |
| The KPA reacts within seconds and uses panic mode under a load jump | That the target concurrency is reached exactly; here 6 pods instead of ≈ 8 |
| Traffic split, tag routes and rollback by traffic work without a new revision | Gradual rollout (`rollout-duration`), or behaviour under load during the switch |
| The request timeout is enforced by the queue-proxy with `504` | Behaviour at the activator for long requests during a cold start; WebSocket/streaming |
| Knative's idle cost is small in usage but large in requests (1750m CPU) | Overhead at scale (many services, many revisions) |

## Deviations from BRIEF

1. **S3–S5 ran on `podinfo` with `autoscaling.knative.dev/window: 6s`** (revision `00002`, B11 allows it). S1 and S2 ran on revision `00001` with the defaults.
2. **S6 had no warm-up**, so the scale-up from 0 is part of the series. Pods were sampled every 2.3 s on average instead of every 2 s, because each sample makes three API calls.
3. **Script defects that were fixed and re-run or re-evaluated** (the raw data was kept):
   - S3's first evaluation was empty, because the "already present" Pulled message did not match the pull regex and jq then dropped the whole object. The cold-start evaluation now runs from the TSV (`coldstart-eval`), and the S3 TSV was re-evaluated. The empty S3 line was removed from `measurements.json`.
   - S5's first run: fortio's stderr line "Successfully wrote … Json data" landed inside the JSON in `kubectl logs`. The extractor now keeps only the indented JSON block. S5 was re-run, and the broken raw file was deleted.
   - S10's first run measured the namespaces (raw file `resources-s10-knative-1.24-20261031T100819Z.txt`, kept, plus its line in `resources.jsonl`), but writing the record failed. Bash 3.2 brace-expanded an awk format inside a nested `$(...)`. The node stats moved into a function, and S10 was re-run completely.
   - During S2 I edited `measure-serving.sh` while it ran, which made bash report a syntax error at the end of the run. The S2 record had already been written.
4. **`successThreshold: 1`** was added to the S8 manifests after the finding above.
5. New targets beyond B8: `apps-serving-fastdown`, `apps-serving-exp`, `apps-serving-down`, `exp-s8`, `exp-s9`, `coldstart-eval`, `node-image`. `snapshot-resources.sh` now also writes node usage into `resources.jsonl`.
6. **Guardrail slip (B4 rule 2), no effect:** during the S8 analysis one ad-hoc command contained `.local/bin/kubectl --kubeconfig=/dev/null version`, a leftover with no purpose. With `/dev/null` as kubeconfig it reached no cluster and changed nothing. It still violates the rule against `--kubeconfig` and is recorded here.
7. `make lint-server` fails on `apps/upgrade/u2-events.yaml`, because the namespace `ok211-events` was removed after Phase 4 and the dry run of namespaced objects needs it. This is known and left as is.
