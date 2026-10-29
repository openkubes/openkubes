# OK-167 — Gitless GitOps with Argo CD and zot

**Status: in progress.** Scaffold and guards are in place (Phase 1 of 12). The cluster,
registry, pipeline and the evaluation report are not built yet. Nothing in this directory
should be read as a result until `REPORT.md` exists.

| | |
|---|---|
| Ticket | [OK-167](https://kubernauts.atlassian.net/browse/OK-167) |
| ADR under evaluation | `ADR-Platform-011` (GitOps), with `ADR-Platform-028` (Artifact Registry) as the second yardstick |
| Assignment | [`BRIEF.md`](BRIEF.md) — binding, German |
| Evidence | [`evidence/`](evidence/) |

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

Targets for the cluster, zot, the packaging pipeline and Argo CD arrive with their phases;
this README is updated as each lands. `make install` will run the full stack in one step and
`make down` will delete the cluster while keeping `.local/`.

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
| `scripts/` | `guard.sh`, `scan-secrets.sh`, `lib.sh`; the packaging pipeline and measurement follow in Phase 4 and 7. |
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

A third observation concerns `registry-default` directly and is still open: the zot chart
documents an `authHeader` value needed for the Kubernetes probes when htpasswd authentication
is on and anonymous access is not, and `values-ok-shared.yaml` sets no such value while using
`defaultPolicy: []`. Whether that is a latent problem there, or whether zot exempts its health
endpoints from authentication, is measured in Phase 3 rather than guessed. See finding F5 in
`evidence/00-preflight.md`.
