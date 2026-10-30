# 08 — Q2: artifact structure constraints

> Historical record from 2026-10-29. Review findings and the 2026-10-30 retest are documented in [12-review-remediation.md](12-review-remediation.md). Original observations below are retained; they do not certify the revised implementation.

- Test IDs: S-A – S-J
- Date (UTC): 2026-10-29T12:25Z – 12:32Z
- Environment: Argo CD v3.5.6

## Results

| ID | Case | Result | Argo CD's exact words |
|---|---|---|---|
| S-A | directory packed by `oras push .` itself | **syncs**, 2 resources | — |
| S-B | `tar+gzip` from the pipeline | **syncs**, 2 resources | — (the main path, Phase 6) |
| S-C | Kustomize `base/` + `overlays/poc`, `path: overlays/poc` | **syncs**, 2 resources | — |
| S-D | Helm chart mirrored into zot | **NOT RUN** — see below | — |
| S-E | two `tar+gzip` content layers | **rejected** | `expected only a single oci content layer, got 2` |
| S-F | a layer that is not an archive (`application/yaml`) | **rejected** | `expected only a single oci content layer, got 0` |
| S-G | same artifact without `--artifact-type` | **syncs** | — |
| S-H | referrer (SBOM, then signature) on the subject | **syncs**, revision unchanged | — |
| S-I(1) | uncompressed `application/vnd.oci.image.layer.v1.tar` | **syncs**, 2 resources | — |
| S-I(2) | custom layer media type, before configuration | **rejected** | `oci layer media type application/vnd.openkubes.manifests.layer.v1.tar+gzip is not in the list of allowed media types` |
| S-I(2) | same, after adding it to the allowlist | **syncs**, 2 resources | — |
| S-J | Kustomize with remote bases | documentation only | — |

All three error strings predicted in Appendix A were reproduced **verbatim**.

## Details worth carrying into the report

### S-A — oras packs a directory into one layer

`cd app/podinfo-plain && oras push <ref> .` produces a single `tar+gzip` layer whose title is
`.`, and `artifactType` defaults to `application/vnd.unknown.artifact.v1`. Argo CD finds both
resources. So the pipeline is not strictly required — but it is what adds the provenance
annotations and the reproducible digest, which is the entire point of M3 and K3.

### S-G — `--artifact-type` is not load-bearing

Without it, oras sets `application/vnd.unknown.artifact.v1` and Argo CD syncs anyway. Argo CD
dispatches on the **layer** media type, not the artifact type. A custom artifact type is
therefore useful for *your* tooling and policy, not for Argo CD.

### S-I(2) — the allowlist is real and configurable

Before: rejected with the message above. After a Helm upgrade setting

```text
configs.params."reposerver.oci.layer.media.types" =
  application/vnd.oci.image.layer.v1.tar,
  application/vnd.oci.image.layer.v1.tar+gzip,
  application/vnd.cncf.helm.chart.content.v1.tar+gzip,
  application/vnd.openkubes.manifests.layer.v1.tar+gzip
```

plus a repo-server restart: accepted, 2 resources. The setting was then reverted and the
rejection confirmed to return — the reset was verified, not assumed.

**Gotcha:** Helm's `--set-string` treats commas as list separators, so every comma in the value
must be escaped (`\,`). Without that it fails with
`key "tar+gzip" has no value (cannot end with ,)`.

### The AppProject glob — `*` does not cross `/`

The first attempt at S-E and S-F failed for a reason that had nothing to do with layers:

```text
[InvalidSpecError] application repo oci://zot.zot.svc.cluster.local:5000/openkubes/machine/gitops/negative/two-layers
is not permitted in project 'ok167'
```

The project's `sourceRepos` entry ended in `/*`, which does **not** match a nested path. Changing
it to `/**` admitted them and the real layer errors appeared. This is a trap worth reporting:
the symptom looks like a project misconfiguration, not a path-depth problem, and a single `*` is
easy to write by habit.

### S-D — not run

The Helm-chart mirror (`helm pull` from ghcr, `helm push` into zot) was **not executed**. Helm 4
is installed, not Helm 3, and its `helm push` / `helm registry login` flags were not verified
against a TLS registry with a private CA; running it on assumption would have contradicted the
spike's own rule about not guessing CLI behaviour. The AppProject and
`argocd/application-helm.yaml` are prepared for it.

What this costs: the upstream-mirroring example, which matters for the air-gap story, is not
demonstrated. Phase 9 covers the same ground differently — a full artifact round trip through an
OCI layout — so the gap is in breadth, not in the central claim. Recorded as a **proposed
follow-up**, not as a silent omission.

### S-J — remote bases (documentation)

A Kustomize overlay may reference `resources: - https://…`, which Argo CD resolves **at render
time, from the repo-server**. Such an artifact is not hermetic: it looks self-contained in the
registry but needs the public internet to render. For any restricted-network or air-gap use the
rule has to be that artifacts are hermetic, and that is a CI lint, not something Argo CD enforces.

## Answer to Q2

Argo CD v3.5.6 requires **exactly one content layer** whose media type is on the allowlist
(by default `…tar`, `…tar+gzip`, `…helm.chart.content.v1.tar+gzip`). Additional constraints include at most ten total layers, extraction-size limits and
out-of-bounds-symlink rejection. Within those constraints, the recorded variants show that the artifact type is free, extra referrers are ignored, Kustomize renders
from a subdirectory, and the allowlist itself is configurable. The constraint is narrow and the
errors are precise, which makes it easy to build a pipeline against.

## What this proves / What this does not prove

| Proves | Does not prove |
|---|---|
| The single-content-layer rule, with the exact rejection messages | How Argo CD behaves with more than 10 layers — the documented limit was not reached |
| The media-type allowlist is enforced and configurable at runtime | That adding a type is wise; it moves the artifact off the interoperable path |
| Kustomize renders from a path inside the artifact | That remote bases work or fail in a particular way — S-J is documentation only |
| `--artifact-type` does not affect Argo CD's acceptance | That it is useless; it remains the handle for policy and tooling |
| A single `*` in `sourceRepos` does not match nested repositories | The full glob semantics — only this one boundary case was measured |
