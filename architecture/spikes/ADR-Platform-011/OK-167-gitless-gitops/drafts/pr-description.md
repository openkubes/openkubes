<!-- POSTED as the body of https://github.com/openkubes/openkubes/pull/462 on 2026-10-29. Do not post again. -->

## Summary

Spike OK-167: can Argo CD take an OCI artifact in a zot registry as an `Application` source
instead of a Git repository? Yes, and the evidence is here. All four locally testable acceptance
criteria pass. Two gaps keep it short of an unconditional recommendation: Argo CD v3.5.6 does no
signature verification on OCI sources, and it cannot consume zot's CloudEvents.

**Proposed outcome: CONDITIONAL GO** for the `datacenter` envelope. The decision belongs to the
three-way review, not to this PR.

This touches **only** `architecture/spikes/ADR-Platform-011/OK-167-gitless-gitops/`. No ADR, no
`platform/registry/zot/`, no `platform/gitops/`, and nothing under `.github/workflows/` — the
GitHub Actions example lives in `ci/` precisely so it cannot run.

## What is here

| Path | What |
|---|---|
| `REPORT.md` | The evaluation report (D3), source for Confluence |
| `evidence/00…11` | One document per phase, each with a "proves / does not prove" section |
| `scripts/package-and-push.sh` | D1 — deterministic packaging and push |
| `argocd/application-*.yaml` | D2 — tag, digest, SemVer, Kustomize and Helm variants, each commented |
| `zot/values-poc.yaml` + `DEVIATIONS.md` | zot config and every difference from `registry-default`, with reasons |
| `Makefile` | The only entry point; every cluster-touching target runs the context guard first |
| `ci/github-actions-example.yaml` | D1 CI variant, `actionlint`-clean, deliberately not active |

## Reproduction

```sh
cd architecture/spikes/ADR-Platform-011/OK-167-gitless-gitops
export KUBECONFIG="$PWD/.local/kubeconfig"
make help          # every target
make preflight     # no cluster needed
make up zot-install argocd-install
make push VARIANT=plain TAG=v1.0.0 && make app-tag && make app-wait APP=ok167-podinfo-tag
make down
```

Each tool resolves through its own Make variable, so any of them can be swapped for a pinned
container wrapper without touching a target.

## Results

| AC | Verdict |
|---|---|
| AC1 zot with TLS, identities, authorization | PASS (V1–V8) |
| AC2 oras packaging as `tar+gzip` | PASS, digests reproducible |
| AC3 Application with `oci://` repoURL | PASS |
| AC4 change detection and live reconciliation | PASS — 83/119/182 s, no intervention |
| AC5 Confluence documentation | PENDING until published |

| Criterion | | |
|---|---|---|
| M1 AC1–AC4 with TLS and auth, no insecure flags | Must | **MET** |
| M2 no secret value in Git | Must | **MET** |
| M3 artifact traceable to a commit | Must | **MET** |
| M4 detection without manual intervention | Must | **MET** |
| K1 push refresh without a self-built bridge | Can | **NOT MET** |
| K2 signature verification that prevents a sync | Can | **NOT MET** |
| K3 deterministic digests | Can | **MET** |
| K4 offline transfer with referrers | Can | **MET** |

## What this does not prove

- **Nothing here establishes an air-gapped envelope.** ADR-017 defines none and ADR-028 §4.9 says
  an offline-transfer proof does not create one. One 28 KB artifact moved between two
  repositories on one host.
- **No workload image was ever pulled from zot.** Containerd trust on the nodes is an explicit
  non-goal, so podinfo still comes from ghcr.io.
- **Nothing about scale.** One Application, one repository, one node, one laptop.
- **Git polling was not measured** — there was no Git source to compare against, so the Q3
  comparison is structural, not numerical.
- Five items are recorded as **NOT RUN with reasons** rather than quietly skipped: S-D, Q1.e,
  Q3.a, Q3.d, Q3.e.

## Three findings that outlive the spike

1. **`registry-default` has no latent probe problem.** The zot chart documents an `authHeader`
   for probes under htpasswd-without-anonymous, and `values-ok-shared.yaml` sets none. Measured
   rather than assumed: zot v2.1.20 exempts its health endpoints from access control.
2. **Legacy cosign signatures do not survive `oras cp -r`** — they are tags, not referrers, and
   the loss is silent. Relevant to ADR-028 §4.6.
3. **`platform/gitops/README.md` recommends Flux while ADR-011 proposes Argo CD.** Reported, not
   resolved.

## Proposed recommendation

**CONDITIONAL GO**, conditional on a CI promotion gate that verifies signatures and promotes by
digest, digest-pinned Applications in operation, and a decision on push-based refresh. Details
in `REPORT.md` §12.

## Checklist

- [x] `make lint`, `make scan-secrets`, `make verify` green
- [x] No changes outside the spike directory
- [x] No file under `.github/workflows/`
- [x] No secret value in the branch history (scanned)
- [x] Every version and digest pinned in `versions.env`
- [x] Cluster torn down; `.local/` retained and gitignored
- [ ] `REPORT.md` published to Confluence (closes AC5) — human action
- [ ] Three-way review of the recommendation — Gawenda / Arash

🤖 Generated with [Claude Code](https://claude.com/claude-code)
