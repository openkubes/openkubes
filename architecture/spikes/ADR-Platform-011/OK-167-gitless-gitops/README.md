# OK-167 — Gitless GitOps with Argo CD and zot

**Status: complete, pending review.** All four locally testable acceptance criteria pass.
The proposed recommendation is **CONDITIONAL GO** for the `datacenter` envelope — see
[`REPORT.md`](REPORT.md) §12. The decision belongs to the three-way review, not to this
directory.

- Report in Confluence: https://kubernauts.atlassian.net/wiki/spaces/OpenKubes/pages/3179446273
- Draft pull request: https://github.com/openkubes/openkubes/pull/462

| | |
|---|---|
| Ticket | [OK-167](https://kubernauts.atlassian.net/browse/OK-167) |
| ADR under evaluation | `ADR-Platform-011` (GitOps), with `ADR-Platform-028` (Artifact Registry) as the second yardstick |
| Assignment | [`BRIEF.md`](BRIEF.md) — binding, German |
| Report (D3) | [`REPORT.md`](REPORT.md) |
| Evidence | [`evidence/`](evidence/) — `00-preflight` through `11-offline-transfer` |
| Drafts (now published) | [`drafts/`](drafts/) — Jira comment and PR description, both posted |

## What this spike asks

Argo CD can take an OCI artifact as an `Application` source instead of a Git repository.
This spike builds that end to end against a local [zot](https://zotregistry.dev) registry
and measures whether it holds up: Kubernetes manifests are packaged by CI into a single-layer
`tar+gzip` OCI artifact, pushed to zot, and synchronised from there by Argo CD.

"Gitless" names the delivery channel, not the source of truth. Git remains the source of
truth (ADR-011 §1); the registry becomes the transport. The consequence is the spike's central
requirement: **every artifact must be traceable back to a Git commit** through the
`org.opencontainers.image.source` and `.revision` annotations.

## Safety model

This spike runs entirely on a local kind cluster and must never reach an OpenKubes cluster.
That is enforced, not merely intended:

- `KUBECONFIG` points only at `.local/kubeconfig`, which exists only inside this directory.
- [`scripts/guard.sh`](scripts/guard.sh) runs before every target that reads or changes a
  cluster. It rejects a missing, relative, multi-path or foreign `KUBECONFIG`, a kubeconfig
  holding more than one context, a context other than `kind-ok167`, an API server that is not
  on `https://127.0.0.1:`, a `kubectl` more than one minor version from the cluster, and paths
  that escape `.local/` through `..` or a symlink.
- Every credential lives in `.local/` at mode 600. `.local/` is gitignored.
- [`scripts/scan-secrets.sh`](scripts/scan-secrets.sh) runs before every commit.

See [`evidence/00-preflight.md`](evidence/00-preflight.md) for the guard's test results,
including the two escapes that were found and closed while testing it.

## Reproduction

Requires a Docker-compatible runtime with at least 6 GB of memory, and the toolchain listed in
`evidence/00-preflight.md`. From this directory:

```sh
export KUBECONFIG="$PWD/.local/kubeconfig"

make help            # every target, with a description
make preflight       # tools, versions, architecture, ports, pins — no cluster needed
make lint            # shellcheck + yamllint
make scan-secrets    # credential scan over tracked and staged files
```

Full run, from nothing to a working stack:

```sh
make up                             # kind cluster, loopback only
make namespaces pki identities      # PKI and machine identities into .local/
make events-install                 # CloudEvents sink (before zot, on purpose)
make zot-install                    # asserts the image pin and that no chart Secret renders
make zot-verify                     # V1-V8
make argocd-install                 # asserts every image is digest-pinned
make argocd-repo REPO=podinfo-manifests
make argocd-project

make push VARIANT=plain TAG=v1.0.0
make app-tag
make app-wait APP=ok167-podinfo-tag
make probe-version NS=ok167-demo    # podinfo reports its own version

make verify                         # re-check every pass criterion
make down                           # delete the cluster; .local/ is kept
```

Every tool resolves through its own Make variable, so any of them can be replaced by a pinned
container wrapper without touching a target:

```sh
make lint YAMLLINT='docker run --rm -v "$PWD":/w -w /w <pinned-image> yamllint'
```

## Layout

| Path | What |
|---|---|
| `BRIEF.md` | The assignment. Binding; committed unchanged. |
| `versions.env` | Every version and digest. The only place pins are maintained. |
| `Makefile` | The only entry point. No target touches a cluster without the guard. |
| `scripts/` | `guard.sh`, `scan-secrets.sh`, `lib.sh`, `pki.sh`, `identities.sh`, `zot-verify.sh`, `package-and-push.sh` (D1), `measure-sync.sh`. |
| `argocd/` | D2 — Application variants (tag, digest, SemVer, Kustomize, Helm), AppProject, Secret template. |
| `ci/` | GitHub Actions example. Outside `.github/workflows/` on purpose. |
| `diagrams/` | Architecture diagram, Mermaid source plus SVG for Confluence. |
| `evidence/` | One document per phase, in the format of `docs/agentic-ai-poc-evidence-protocol.md`. |
| `evidence/raw/` | Redacted command output. |
| `.local/` | **Never committed.** kubeconfig, PKI, credentials, Helm state, cosign keys. |

## Notes for readers of this repository

The spike directory is the only thing it changes. It does not modify any ADR,
`platform/registry/zot/`, `platform/gitops/`, or anything under `.github/workflows/` — the
GitHub Actions example lives in `ci/` precisely so that it cannot run.

Two pre-existing inconsistencies were found while reading and are reported rather than fixed,
because fixing them is not this spike's job:

- `platform/gitops/README.md` recommends Flux, while ADR-011 proposes Argo CD and records Flux
  as the rejected alternative.
- ADR-028 §4.4 describes a logical namespace of `openkubes/{platform,cluster,…}/`, while the
  deployed `registry-default` profile uses `openkubes/{human,machine}/**`. This spike follows
  the deployed profile, since that is what it must interoperate with.

A third observation concerned `registry-default` directly and is now **closed in its favour** —
see "Findings that outlive the spike" below, item 1.

## Results in one table

| AC | Verdict | | Criterion | Verdict |
|---|---|---|---|---|
| AC1 zot with TLS, identities, authorization | **PASS** | | M1 AC1–AC4, TLS, no insecure flags | **MET** |
| AC2 oras packaging as `tar+gzip` | **PASS** | | M2 no secret value in Git | **MET** |
| AC3 Application with `oci://` repoURL | **PASS** | | M3 artifact traceable to a commit | **MET** |
| AC4 change detection, live reconciliation | **PASS** | | M4 detection without intervention | **MET** |
| AC5 Confluence documentation | **DONE** | | K1 push refresh without a bridge | NOT MET |
| | | | K2 verification that blocks a sync | NOT MET |
| | | | K3 deterministic digests | **MET** |
| | | | K4 offline transfer with referrers | **MET** |

Detection latency, measured: **83 / 119 / 182 s** by polling at the defaults, **0 s** with an
on-demand refresh, **1 s** for cluster drift. Three different mechanisms — see
[`evidence/06-sync.md`](evidence/06-sync.md).

## Findings that outlive the spike

1. **`registry-default` has no latent probe problem.** The zot chart documents an `authHeader`
   for probes under htpasswd-without-anonymous access, and `values-ok-shared.yaml` sets none.
   Measured rather than assumed: zot v2.1.20 exempts `/livez`, `/readyz` and `/startupz` from
   access control, returning 200 anonymously while `/v2/` returns 401.
2. **A digest pin does not keep an artifact alive.** A digest-pinned Application here broke
   because the manifest was garbage-collected once its tag moved away. `registry-default` runs
   with `gc: true` and `Retention.Policies: null` — the retention definition ADR-028 §4.7 asks
   for does not exist yet.
3. **Legacy cosign signatures are silently lost in transfer.** They are tags, not referrers, so
   `oras cp -r` drops them and the copy then fails verification with nothing reporting a problem.
   Awkwardly, zot only *verifies* that legacy format, while only the bundle format survives.
4. **Argo CD v3.5.6 does no signature verification on OCI sources.** Unsigned content synced with
   zero conditions. Signing is evidence, not enforcement.
