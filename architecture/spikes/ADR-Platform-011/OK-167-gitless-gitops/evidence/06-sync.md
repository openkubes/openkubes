# 06 — Change detection and live reconciliation (AC4)

- Test IDs: T1–T8
- Date (UTC): 2026-10-29T12:13Z – 12:35Z
- Worktree commit: `a7cb664`
- Environment: Argo CD v3.5.6 (`timeout.reconciliation: 120s`, jitter `60s`), zot v2.1.20
- Raw measurements: `evidence/raw/measurements.json`

## Method

`scripts/measure-sync.sh` polls the Application once a second and records, relative to the
moment the push returned:

| | |
|---|---|
| `detection` | `status.sync.revision` equals the new digest |
| `sync` | the sync operation reports `Succeeded` **for that revision** |
| `healthy` | `status.health.status` is `Healthy` **and** synced to the new revision |
| `rollout` | every running pod carries the expected image, counted against `spec.replicas` |

`rollout` is measured against the **pods**, not the Deployment spec: the spec updates the instant
Argo CD applies it, while the pods take longer. Every row records the reconciliation settings it
ran under.

## Results

### T1 — mutable tag, no intervention whatsoever (the AC4 proof)

Three pushes to the **same tag** `v1.0.0`, alternating between podinfo 6.16.0/1 replica and
6.17.0/2 replicas. After each push: nothing. No refresh, no restart, no `argocd` command.

| Run | detection | sync | healthy | rollout |
|---|---|---|---|---|
| 1 | 182 s | 182 s | 205 s | 209 s |
| 2 | 83 s | 83 s | 88 s | 93 s |
| 3 | 119 s | 119 s | — | — |
| **min / median / max** | **83 / 119 / 182 s** | | | |

All three are inside the configured window of 120 s + up to 60 s jitter (run 1's 182 s is 2 s
over the theoretical 180 s, within the 1 s polling resolution and the time the push itself took).

The spread is the jitter doing its job: detection latency depends on where in the reconciliation
cycle the push happens to land, so a single measurement would have been meaningless. **The
practical statement is "up to about three minutes", not an average.**

The cluster really changed — verified after run 1 by reading it back:

```text
replicas=2  image=ghcr.io/stefanprodan/podinfo:6.17.0@sha256:fa2f27c1a856…
podinfo /version -> {"version": "6.17.0"}   (from both pods)
```

**T1 PASS. This is the evidence for AC4.**

### T2 — refresh on demand

Same push, followed immediately by `argocd.argoproj.io/refresh=normal`.

| Run | detection | sync | healthy | rollout |
|---|---|---|---|---|
| 1 | 0 s | 1 s | 7 s | 11 s |
| 2 | 0 s | 1 s | 13 s | 17 s |
| 3 | 0 s | 2 s | 7 s | 11 s |

Detection is immediate; the remaining time is the Kubernetes rollout, not Argo CD.

**The contrast is the central number of this spike: 83–182 s by polling versus ~0 s on demand.**
T2 is supplementary and does **not** count as proof of automatic detection — it is the measure of
what a push-based trigger (Q3.d) would be worth.

### T3 — exact tag does not drift

The Application was pinned to `targetRevision: v1.1.0` and allowed to settle. Then `v1.2.0`,
`v1.4.0`, `v1.5.0` and `v2.0.0` were pushed, each a different digest.

After **519 s — two full worst-case polling cycles** — `status.sync.revision` was still
`sha256:627cf3ad…`, the digest `v1.1.0` resolved to. **PASS.**

### T4 — digest pin does not drift

`ok167-podinfo-digest` pinned to `sha256:627cf3ad…`. Same window, same four pushes.
Unchanged after 519 s. **PASS.**

This is the shape the report recommends for operations: only an edit to the Application — a Git
commit, with an author and a review — can change what is deployed.

### T5 — SemVer range

`targetRevision: ">=1.0.0 <2.0.0"` against tags `v1.0.0, v1.1.0, v1.2.0, v1.4.0, v1.5.0`.

- Argo CD selected `v1.5.0` (`sha256:4ebed7a2…`) — the highest **matching** tag.
- `v2.0.0` was then pushed and **ignored**, as the range requires.

Worth recording: the constraint is written without a `v` prefix and the tags carry one. v3.5.6
matches them anyway. **PASS.**

### T6 — rollback by moving the tag back

`oras tag …@sha256:b4eb3ab9… v1.1.0` pointed the tag at an earlier artifact.

| detection | sync | healthy | rollout |
|---|---|---|---|
| 1 s | 2 s | 14 s | 17 s |

Rollback is just another digest change; nothing special is needed. **PASS.**

### T7 — self-heal

`podinfo` in `ok167-kustomize` was scaled from 2 to 5 replicas by hand.
**Reverted to 2 after 1 second.**

This is a different mechanism from everything above and the distinction matters for the report:
**drift in the cluster is noticed immediately, because the controller watches live resources;
a change at the source is noticed only on the next poll.** Quoting one number for "how fast is
Argo CD" would conflate the two. **PASS.**

### T8 — registry outage

| Step | Observation |
|---|---|
| zot scaled to 0 | podinfo keeps serving, 2/2 ready |
| refresh while down (**warm** repo-server) | `Synced` / `Healthy`, **no error at all** — Argo CD answered from cache and did not notice the registry was gone |
| repo-server restarted (**cold** cache), zot still down | `sync=Unknown`, `[ComparisonError] Failed to load target state: … rpc error: code = DeadlineExceeded desc = context deadline exceeded`. `health` stays `Healthy`, the 2 tracked resources stay tracked |
| zot restored | recovered to `Synced` after **77 s**, **no refresh issued** |
| throughout | podinfo 2/2 ready, **0 container restarts** |

**PASS**, and the most edge-relevant result in the spike. Three things follow:

1. **Running workloads are unaffected by a registry outage.** They are already applied; the
   registry is only needed to render desired state.
2. **A warm cache hides the outage completely.** Monitoring the Application's health would not
   have detected it. Registry availability needs its own alert.
3. **A cold repo-server plus an unreachable registry means no reconciliation is possible** —
   the failure is a timeout, not a clear "registry unreachable". For `constrained-edge`, where
   the registry is in a datacenter the node may not reach, this is the governing constraint.

## AC4 verdict

**PASS.** T1 (automatic detection with no intervention), T3 and T4 are all proven, which is what
the brief names as the requirement. T2, T5, T6, T7 and T8 all pass as well.

**M4 is met**: changes are detected without manual action inside the configured reconciliation
window.

## What this proves / What this does not prove

| Proves | Does not prove |
|---|---|
| Argo CD detects a new digest under an unchanged tag with no intervention, in 83–182 s at the default settings | That this scales — one Application, one repository, one node. Many Applications sharing a repo-server is untested |
| The latency is governed by the reconciliation timeout and its jitter, not by registry speed | What the figures would be at other settings — Q3.a measures 30 s/0 s separately |
| An exact tag and a digest pin both hold still across two full polling cycles | That they hold indefinitely, or under a registry that reuses digests |
| A SemVer range picks the highest matching tag and ignores one outside it | How quickly it picks up a *new* matching tag — the tag list is cached (Q3.e) |
| Self-heal reverts cluster drift within a second | That it protects against anything but drift; it does not verify the source |
| Workloads survive a full registry outage with zero restarts | That a *new* workload could start — no image pull from zot was attempted (explicit non-goal) |
| A cold repo-server cannot render without the registry, and says `DeadlineExceeded` | That the message would be the same for other failure modes (DNS, auth, TLS) — Q1.c and Q1.d test those |

---

## T4 addendum — a digest pin does not keep the artifact alive

Found while running `make verify` at the end of the spike, not during T4 itself.

`ok167-podinfo-digest`, pinned to `sha256:627cf3ad…`, had moved from `Synced` to `Unknown`:

```text
[ComparisonError] Failed to load target state: failed to generate manifest for source 1 of 1:
rpc error: code = Unknown desc = failed to resolve revision "sha256:627cf3ad…":
cannot get digest for revision sha256:627cf3ad…:
zot.zot.svc.cluster.local:5000/openkubes/machine/gitops/podinfo-manifests@sha256:627cf3ad…: not found
```

**The manifest was gone from the registry.** Not corrupted, not unauthorized — absent.

### Mechanism

1. During Q4.c the tag `v1.1.0` was moved to different content.
2. `sha256:627cf3ad…` thereby became **untagged**. Confirmed: zero of the six tags in the
   repository resolve to it.
3. zot's garbage collection ran, as its own log shows:

   ```text
   12:36:58  executing gc of orphaned blobs for /var/lib/registry/openkubes/machine/gitops/podinfo-manifests
   12:36:58  garbage collected blobs
   12:36:58  gc successfully completed for …
   ```

4. The Application's digest pin was the **only** remaining reference to that manifest — and the
   registry has no way to know it exists.

Re-pinning to `sha256:b4eb3ab9…`, which is still tagged `v1.2.0`, returned the Application to
`Synced` / `Healthy` immediately.

### Why this matters more than a test artifact

This directly qualifies the recommendation the spike was about to make. "Pin digests in
operation" is necessary but **not sufficient**: a digest pin expresses *which* artifact you
want, and expresses nothing about *keeping* it. Retention is a separate, registry-side concern,
and nothing in the cluster communicates its dependencies back to the registry.

The configuration in effect during this spike — inherited from `registry-default` — is:

```json
"storage": { "gc": true, "gcDelay": "1h", "gcInterval": "1h" },
"Retention": { "Policies": null }
```

**No retention policy is configured**, here or in `values-ok-shared.yaml`. ADR-028 §4.7 requires
the profile to define "tag immutability, release/staging/quarantine retention, garbage-collection
behaviour, deletion authorization, and an emergency-deletion procedure". This is a concrete
demonstration of what the absence of that definition costs: an artifact a cluster is actively
running can be collected because nothing in the registry marks it as released.

§4.7 also says GC "MUST NOT remove blobs still reachable from a retained manifest". The clause
holds — the manifest was not *retained*, because nothing retained it. The gap is not a violation;
it is the missing definition of what "retained" means for an artifact that is deployed.

### Correct operating guidance

Digest-pinned Applications **plus** one of:

- keep an immutable release tag on every digest that is deployed (so the registry retains it), or
- configure a retention policy that keeps released artifacts regardless of tags, or
- treat the untagging of a deployed digest as a release-process error, caught in CI.

Verdict: **T4 still PASSES** — the pin did not drift, which is what T4 tested. This is a separate
failure mode, found only because `verify` re-checked the state later, and it is more useful than
the original test.
