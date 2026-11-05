# 09 — Q3: detection, caching and webhooks

> Historical record from 2026-10-29. Review findings and the 2026-10-30 retest are documented in [12-review-remediation.md](12-review-remediation.md). Original observations below are retained; they do not certify the revised implementation.

- Test IDs: Q3.b, Q3.c (plus T1/T2 from `06-sync.md`)
- Date (UTC): 2026-10-29T11:54Z – 12:31Z
- Environment: Argo CD v3.5.6 (`timeout.reconciliation: 120s`, jitter `60s`), zot v2.1.20

## Q3 — the measured comparison

| Path | Detection latency | Source |
|---|---|---|
| Polling, defaults (120 s + 60 s jitter) | **83 / 119 / 182 s** (min/median/max, n=3) | T1 |
| Refresh on demand (`argocd.argoproj.io/refresh=normal`) | **0 s** (n=3) | T2 |
| Cluster drift (self-heal) | **1 s** | T7 |

The three are different mechanisms and should never be quoted as one number:

- **Source change** is found by polling, so latency is a function of the reconciliation timeout
  and its jitter, not of registry speed. The spread across three runs is the jitter.
- **Cluster drift** is found by watching live resources, so it is near-instant.
- **On demand** bypasses the wait entirely.

This answers the ticket's framing question: **OCI and Git sources use the same configured reconciliation loop. This is a structural
comparison; equal numerical latency was not established.** Argo CD does not treat an OCI source specially; it
resolves the tag with a `HEAD` request each cycle and compares digests.

Git polling was **not measured** in this spike — there was no Git source to compare against — so
the comparison is structural, not numerical. Saying "OCI is as fast as Git" would be an
unmeasured claim; what can be said is that both run on the same timer.

## Q3.b — zot's CloudEvents

Captured in full: `evidence/raw/cloudevent-image-updated.json`.

| Header | Value |
|---|---|
| `ce-type` | `zotregistry.image.updated` |
| `ce-source` | `zotregistry.dev` |
| `ce-specversion` | `1.0` |
| `ce-id`, `ce-time` | per event |

Body keys: `actor`, `digest`, `manifest`, `mediaType`, `name`, `reference`, `request` — that is
the repository (`name`), the tag (`reference`), the digest, and the pushing identity
(`actor.name`). Everything a refresh bridge would need is present.

Event types observed across the run: `zotregistry.image.updated` (6×),
`zotregistry.repository.created` (1×).

**Delivery is prompt** — the receiver logged the event in the same second as the push
(`ce-time` 11:54:49.608, push completed 11:54:49). Note the repository travels in the **body**,
not in a `ce-subject` header, so a bridge has to parse JSON rather than route on headers alone.

## Q3.c — Argo CD cannot consume them

The captured event was replayed against `argocd-server`'s webhook endpoint from inside the
cluster, with the `ce-*` headers intact:

```text
POST http://argocd-server.argocd.svc.cluster.local/api/webhook
-> HTTP 400
   Unknown webhook event
```

and the server's own log is explicit about what it does support:

```text
level=warning msg="GHCR webhook secret is not configured; incoming webhook events will not be validated"
```

**v3.5.6 understands GHCR webhooks for OCI and nothing else.** zot emits well-formed CloudEvents;
Argo CD has no handler for them. The two are not connectable without something in between.

## Q3.a and Q3.e — not run

- **Q3.a** (reconciliation at 30 s / jitter 0, plus a 10-minute idle comparison of zot request
  counters) was **not executed**. T1 and T2 already bracket the achievable range — 83–182 s at
  the defaults versus 0 s on demand — and a 30 s setting would land predictably between them
  while raising registry load proportionally. Running it would sharpen a number that does not
  change the recommendation.
- **Q3.e** (tag-list cache behaviour under SemVer constraints, comparing `normal` and `hard`
  refresh) was **not executed**. T5 established that SemVer selection works and ignores
  out-of-range tags; the cache timing was not isolated.

Both are recorded as **NOT RUN with reason**, not as passes. They are proposed follow-ups.

## Q3.d — bridge prototype, not attempted

The optional 90-minute bridge prototype was not built. Q3.b and Q3.c together already establish
both halves of the case: the event carries everything needed, and Argo CD will not accept it
directly. The remaining question is engineering cost and the security of giving a bridge
`patch` on Applications — that is a design decision for the follow-up, not a spike finding.

## Answer to Q3

New-digest detection runs on the same reconciliation loop as Git, so it inherits the same
latency: up to the reconciliation timeout plus jitter, measured here at 83–182 s. An on-demand
refresh collapses that to zero. zot does emit CloudEvents on push, promptly and with full
detail, but Argo CD v3.5.6 cannot consume them — its only OCI webhook support is GHCR. Closing
that gap requires a small bridge that receives the CloudEvent and annotates the matching
Applications, which is feasible but is custom code OpenKubes would own.

## What this proves / What this does not prove

| Proves | Does not prove |
|---|---|
| Polling latency at the default settings, across three runs | Latency at other settings — Q3.a was not run |
| An on-demand refresh is effectively instant | That a bridge would achieve the same end to end — Q3.d was not built |
| zot emits complete CloudEvents promptly on push | That delivery is reliable; no retry, failure or back-pressure behaviour was tested |
| Argo CD v3.5.6 rejects a zot CloudEvent with `400 Unknown webhook event` | That a different payload shape would also be rejected — only zot's own event was replayed |
| Argo CD's OCI webhook support is limited to GHCR in this version | Anything about v3.6, which is a release candidate and out of scope |
