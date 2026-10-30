# 03 — Packaging pipeline (AC2, D1)

> Historical record from 2026-10-29. Review findings and the 2026-10-30 retest are documented in [12-review-remediation.md](12-review-remediation.md). Original observations below are retained; they do not certify the revised implementation.

- Test IDs: Phase 4, P4-DET, M3
- Date (UTC): 2026-10-29T12:03Z
- Worktree commit: `af86dd8`
- Environment: oras 1.3.6, GNU tar 1.35, zot v2.1.20 — see `00-preflight.md`

## Steps

```bash
make determinism VARIANT=plain TAG=v1.0.0     # P4-DET, three dry runs
make push VARIANT=plain TAG=v1.0.0            # twice, to compare manifest digests
oras manifest fetch 127.0.0.1:30500/openkubes/machine/gitops/podinfo-manifests:v1.0.0 \
  --ca-file .local/pki/ca.crt --registry-config .local/registry-auth/gitops-publisher.json
actionlint ci/github-actions-example.yaml
```

## Observed

### Artifact structure — AC2

```json
{
  "artifactType": "application/vnd.openkubes.gitops.manifests.v1+tar",
  "layer_count": 1,
  "layers": [
    { "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
      "size": 1036, "title": "manifests.tar.gz" }
  ],
  "annotations": {
    "org.opencontainers.image.created":     "2026-10-29T12:02:44Z",
    "org.opencontainers.image.description": "OK-167 GitOps manifests packaged from app/podinfo-plain",
    "org.opencontainers.image.revision":    "af86dd805bd3056b4a9c4562b3d6c7450223b11b",
    "org.opencontainers.image.source":      "https://github.com/openkubes/openkubes",
    "org.opencontainers.image.title":       "podinfo-plain",
    "org.opencontainers.image.version":     "v1.0.0"
  }
}
```

Exactly one content layer, `tar+gzip`, with all six annotations. PASS.

### P4-DET — determinism

| Test | Runs | Result |
|---|---|---|
| Layer digest, same input | 3 | `sha256:6d65a089bc96cb81…` — **identical every time** |
| Manifest digest, same input pushed twice | 2 | `sha256:a798ce49915565b1…` — **identical** |

Both the archive and the manifest are reproducible, so **K3 is met**. The manifest staying stable
matters as much as the layer: a tool that stamped a build time into the manifest would produce a
new digest for unchanged content, and every push would look like a change to Argo CD.

What makes it reproducible, with the failure each flag prevents:

| Flag | Without it |
|---|---|
| `--sort=name` | member order follows directory order, which is not stable |
| `--mtime=@$SOURCE_DATE_EPOCH` | the clock enters the digest; every build differs |
| `--owner=0 --group=0 --numeric-owner` | the building user's uid enters the digest |
| `--mode=go+u,go-w` | Original intent only: owner permissions still affected the archive; fixed by packaging the Git tree with explicit normalized modes |
| `--format=posix` + `--pax-option=…delete=atime,delete=ctime` | atime changes on every read |
| `gzip -n` | gzip stores the input filename and the current time in its header |
| `.created` from the commit, not `date` | the manifest changes on every push |

### M3 — traceability, checked rather than assumed

The annotation's presence proves nothing by itself; what matters is whether it is *true*:

```text
revision annotation: af86dd805bd3056b4a9c4562b3d6c7450223b11b
that commit exists:  commit
git diff af86dd8 -- app/podinfo-plain  ->  (empty)
```

The commit named by the artifact contains byte-identical content to what was packaged.
**M3 is met in substance, not only in form.**

The original enforcement claim is withdrawn. Git status omitted ignored files and
`assume-unchanged` changes, while tar included their filesystem bytes. The independent review
rebuilt all 17 recorded pushes successfully, so the recorded examples remain valid; the
universal enforcement claim did not follow from them. The revised implementation materializes
and validates the named Git tree and compares the complete source directory before packaging.
See `12-review-remediation.md` for the regression cases and fresh verification.

### Validation gates

The script fails closed before anything is pushed:

- `yamllint` over the source directory
- `kubectl kustomize` for every directory in the artifact holding a `kustomization.yaml`
  (so for the Kustomize variant, both `overlays/poc` and `overlays/poc-update`)
- GNU tar is asserted — not merely preferred. macOS bsdtar cannot sort archive members, so on
  stock macOS the script stops rather than producing an archive whose digest depends on
  directory order.

Exit codes: 2 validation, 3 authentication, 4 push.

### Credential handling

No password is ever an argument. `oras login` reads `--password-stdin`, the token is written to
`.local/registry-auth/gitops-publisher.json` via `--registry-config`, and nothing touches
`~/.docker`. The push record under `evidence/raw/push-*.json` contains references, digests and
provenance only.

### `ci/github-actions-example.yaml` — D1, CI variant

`actionlint` clean, `yamllint` clean. Not under `.github/workflows/`, verified: the repository's
`.github/` tree is unchanged by this branch.

Both actions are pinned by commit SHA, resolved with `git ls-remote` rather than copied from
documentation:

| Action | Tag | Pinned SHA |
|---|---|---|
| `actions/checkout` | v7 | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| `oras-project/setup-oras` | v2 | `5e2f2482b30b0cb3e14e67f89a80c88c659a7c63` |

The example sets `fetch-depth: 0` deliberately: a shallow clone cannot answer "which commit last
touched this directory", so `SOURCE_DATE_EPOCH` would be empty and the script would refuse to run.
That is a real trap for anyone copying this into a pipeline.

## Verdict

**PASS — AC2 and D1 are met.** Single-layer `tar+gzip` artifacts with full provenance, reproducible
layer and manifest digests, validation before publication, and a CI example that validates clean
and cannot run by accident.

## What this proves / What this does not prove

| Proves | Does not prove |
|---|---|
| The same input yields the same layer and manifest digest on this host | That it does so on another OS or another tar/gzip build — only GNU tar 1.35 on macOS arm64 was tested |
| The revision annotation names a commit whose content is byte-identical to the artifact | That anyone verifies this at pull time; nothing in Argo CD checks the annotation |
| The original sampled source was clean; the original universal refusal claim was false | That `--allow-dirty` artifacts are prevented downstream — they are only labelled |
| yamllint and kustomize run before any push | That the manifests are correct, only that they parse and render |
| No credential appears in arguments, output or the push record | That the registry token in `.local/registry-auth/` is protected beyond file permissions |
| The CI example is syntactically valid and pins its actions by SHA | That it works — it has never been executed, by design |
