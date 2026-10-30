# OK-167 — Gitless GitOps with Argo CD and zot

**Status: remediation completed; proposed decision NO-GO.** The fresh unattended detection
series was 141 / 144 / 184s against the configured 180s window. AC4 and M1/M4 are not met;
the original CONDITIONAL GO is withdrawn. See [REPORT.md](REPORT.md) for the
current decision and [the remediation evidence](evidence/12-review-remediation.md) for results.

- [PR #462](https://github.com/openkubes/openkubes/pull/462)
- [Jira OK-167](https://kubernauts.atlassian.net/browse/OK-167)
- [Confluence report](https://kubernauts.atlassian.net/wiki/spaces/OpenKubes/pages/3179446273)
- [Original binding assignment](BRIEF.md), supplied in German and retained unchanged

## Purpose and boundaries

Test whether Argo CD can use a private zot OCI repository as its Application source.
Git remains the source of truth; OCI delivers the committed manifests. This is a local kind
spike for the datacenter evaluation. It does not change production, define an air-gapped
envelope or implement Vault/VSO integration.

## Safety and packaging

- Use only `kind-ok167` and this directory's ignored `.local/kubeconfig`.
- Every cluster target runs the guard. It validates the complete HTTPS loopback URL and port,
  rejects external paths/plugins/proxies and verifies kubectl version skew. `make guard`
  does not export that environment to later shell commands; use the diagnostic targets.
- Credentials and private keys stay under `.local/`. The Secret helper uses stdin, and no
  target prints an administrator password. Registry and Argo CD API TLS remain enabled.
- Clean packaging compares the source with its named Git tree, including ignored and
  index-hidden changes, then packages the extracted committed bytes with normalized modes.
- `--allow-dirty` is a labelled diagnostic override, not a release path.
- The secret scanner inspects worktree contents and index blobs separately. It does not prove
  the absence of every possible secret format or audit past session behavior.

## Reproduction

Requirements and pins are in `versions.env`; GNU tar, bash 3.2 or newer, kubectl, Helm, oras,
cosign, jq, yq, yamllint and shellcheck must be available. Docker needs sufficient memory for
the isolated cluster. Do not change or delete unrelated clusters.

```sh
export KUBECONFIG="$PWD/.local/kubeconfig"
make help
make lint scan-secrets test-review
make install
make push VARIANT=plain TAG=v1.0.0
make app-tag app-wait APP=ok167-podinfo-tag
make probe-version NS=ok167-demo
make probe-argocd-tls zot-verify verify-artifact
make exp-q1b exp-q1c exp-q1d exp-structure exp-self-heal exp-webhook
make exp-latency                     # three unattended pushes, then three refreshes
make exp-signing                     # prints a signed artifact DIGEST, never a credential
make offline-transfer DIGEST=sha256:<signed-digest>
make exp-recovery verify
make down
```

`make exp-latency` also observes retained exact-tag and digest-pinned Applications for at least
360 seconds. `make sign` / `verify-signature` accept `DIGEST` and `MODE=bundle|legacy`.
`make reconcile REC=30s JITTER=0s` changes the local controller settings; `reconcile-reset`
restores 120s/60s. Having those targets does not mean the alternative settings were evaluated.
Use executable wrapper paths for tool overrides; a quoted string containing a container
command is not a universally supported executable override.

## Evidence and limitations

The current index is [12-review-remediation.md](evidence/12-review-remediation.md).
Documents `00`–`11` are historical records with review corrections. Fresh JSON contains exact
Application revisions/resources, error/recovery states, fetched-byte provenance checks and
absolute timing information. Every claimed retest result must link its retained output.

The original review independently rebuilt all 17 recorded workload artifacts and found no
credential leak across the 11 original commits. It also demonstrated real guard, packaging,
scanner and target-state defects. Those two observations are compatible: valid samples did
not establish the claimed universal guarantees.

No native zot refresh handler or native OCI signature gate was found in Argo CD v3.5.6.
Digest pinning also needs retention: this PoC's retained release tag is not a tested production
policy. Legacy cosign tags need explicit copying; bundle referrers survive recursive transfer.
No workload image was pulled from zot. Helm chart mirroring and the other documented NOT RUN
experiments remain gaps. Production registry and GitOps profile files are unchanged.

The inactive CI example stays in `ci/`; no file is added under `.github/workflows/`.
All revised code, comments, evidence, commits and publication text are English.
