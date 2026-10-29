# 05 — First Application (AC3, D2)

- Test IDs: Phase 6
- Date (UTC): 2026-10-29T12:10Z
- Worktree commit: `a8e904c`
- Environment: Argo CD v3.5.6, zot v2.1.20, podinfo 6.16.0 — see `00-preflight.md`

## Steps

```bash
make push VARIANT=plain TAG=v1.0.0     # -> DIGEST=sha256:a798ce49915565b1...
make app-tag                           # argocd/application-tag.yaml
make app-wait APP=ok167-podinfo-tag
make probe-version NS=ok167-demo
```

## Observed

### Application status

```json
{
  "name": "ok167-podinfo-tag",
  "sync": "Synced",
  "health": "Healthy",
  "revision": "sha256:a798ce49915565b1f38247806f8ab662c521adabcc7c72a01ffe6d9ee4089946",
  "resources": ["Service/podinfo", "Deployment/podinfo"],
  "resource_count": 2,
  "conditions": []
}
```

| Pass criterion | Expected | Observed | Verdict |
|---|---|---|---|
| `status.sync.status` | `Synced` | `Synced` | PASS |
| `status.health.status` | `Healthy` | `Healthy` | PASS |
| `status.resources` | exactly Deployment + Service | exactly those two | PASS |
| `status.sync.revision` | the pushed digest | `sha256:a798ce4991…` — identical to the `DIGEST=` line from `make push` | PASS |
| Deployment image | podinfo 6.16.0 by digest | `ghcr.io/stefanprodan/podinfo:6.16.0@sha256:2c88592f2b8f…` | PASS |
| `/version` | `6.16.0` | `{"version": "6.16.0", "commit": "256d0346…"}` | PASS |
| Replicas | 1 | 1 desired / 1 ready | PASS |

The resource count is part of the criterion on purpose: **Argo CD reports `Synced` even when it
found no resources at all** — a wrong `path`, or files in a subdirectory without
`directory.recurse`, produces a green Application that deployed nothing. Every sync check in this
spike therefore asserts what was actually applied, not just the status word.

### The pull, seen from the registry

zot's access log for the `gitops-puller` identity, which is the direct evidence that Argo CD
reached the registry over TLS with the read-only credential:

```text
  3  HEAD /v2/openkubes/machine/gitops/podinfo-manifests/manifests/v1.0.0            -> 200
  6  HEAD /v2/openkubes/machine/gitops/podinfo-manifests/manifests/sha256:a798ce49…  -> 200
  2  GET  /v2/openkubes/machine/gitops/podinfo-manifests/manifests/sha256:a798ce49…  -> 200
  1  GET  /v2/openkubes/machine/gitops/podinfo-manifests/blobs/sha256:6d65a089…      -> 200
  3  GET  /v2/                                                                        -> 200
```

The tag is resolved with `HEAD` on `manifests/v1.0.0`, then the manifest and the layer are
fetched **by digest** — and `sha256:6d65a089…` is exactly the layer digest the packaging script
reported. The chain from `git commit` → `tar+gzip` → registry → cluster is closed end to end.

## Verdict

**PASS — AC3 is met.** An Argo CD Application with an `oci://` repoURL pointing at zot syncs the
artifact into the cluster, authenticated with a read-only identity, over TLS, with no insecure
flag anywhere.

## What this proves / What this does not prove

| Proves | Does not prove |
|---|---|
| Argo CD v3.5.6 accepts an `oci://` repoURL and syncs the artifact's contents | That it notices a *change* to the artifact — that is AC4, measured in Phase 7 |
| The synced revision is the exact manifest digest that was pushed | That the digest is verified against anything; nothing checks a signature at this point (Q4.e) |
| Exactly the two intended resources were applied | That a wrong `path` would be caught by Argo CD — it would report Synced with zero resources |
| The workload really runs the pinned image, confirmed by podinfo's own `/version` | That the *workload image* came from zot — it is pulled from ghcr.io; containerd trust for zot is an explicit non-goal |
| The repo-server authenticated as `gitops-puller` over TLS | That it would fail without the CA — Q1.d removes it to find out |
