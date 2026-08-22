# OK-171 immutable producer publication

This is the review surface for the first development image of the OpenKubes
Console observed-state producer.

## Publication contract

- Image: `ghcr.io/openkubes/observed-state-producer`
- Trusted event: a `console-observer-dev-v*` tag whose revision is reachable
  from `main`
- Platforms: `linux/amd64` and `linux/arm64`
- Deployment identity: exact published `sha256` digest
- Supply chain: OCI source/revision labels, SPDX SBOM, GitHub build and SBOM
  attestations, keyless Sigstore signature and HIGH/CRITICAL development scan
- Authority: ephemeral GitHub token and OIDC identity only; no long-lived
  registry or signing credential

The workflow fails if the human candidate tag already exists in GHCR. Pull
requests continue to use the read-only verification workflow and cannot invoke
publication authority.

## Source verification

Before a candidate tag is created:

```bash
make -C platform/console/observed-state-producer verify
docker build \
  --build-arg VCS_REF="$(git rev-parse HEAD)" \
  -f platform/console/observed-state-producer/Containerfile \
  -t openkubes-observed-state-producer:ok-171 \
  platform/console/observed-state-producer
```

The pinned Python base is a multi-platform OCI index. The runtime retains the
existing non-root UID `65532`, removes all Python packaging tools and
third-party `site-packages`, contains no application credential, and remains
compatible with the manifest's read-only root filesystem. The producer uses
only the Python standard library.

## Rejected candidate

`console-observer-dev-v0.1.0-rc.1` published image digest
`sha256:f2072ebc0cc21c37a6796022daf337c1d9d102186af1431ac1910ebe9829ca1c`,
but failed closed before attestation and signing. Trivy reported two HIGH
findings in libraries vendored by the otherwise unused runtime `pip` package:

- `msgpack 1.1.2` / `GHSA-6v7p-g79w-8964`;
- `setuptools 70.3.0` / `CVE-2025-47273`.

The candidate is rejected and must never be deployed. Its tag and digest are
retained as failure evidence rather than overwritten. The remediation removes
the complete unused packaging surface and scans before generating the external
SBOM. A later signed candidate must use a new tag.

## Accepted candidate

`console-observer-dev-v0.1.0-rc.2` is the accepted OK-171 development
candidate:

- source revision: `9ad57d333d5b279b232b20fc47769fa635dcdb23` on `main`;
- workflow: [Publish observed-state producer run 32582418848](https://github.com/openkubes/openkubes/actions/runs/32582418848);
- deployment digest: `sha256:e55f1c0576ab3775e7ef32deb4d991b3bed022521c5ed2ffae29241c120acffa`;
- `linux/amd64`: `sha256:a0fc332a72b1bc791a1e1025f825d0bd5d69861d58b0cb65a5f1e76189413290`;
- `linux/arm64`: `sha256:f20e3a69d296eec78374ff0069586cdf5e3a8efb1f8962f562f852050084aef6`.

The workflow passed source reachability, unit and manifest tests, multi-platform
build and publication, the HIGH/CRITICAL Trivy gate, SPDX SBOM generation,
GitHub build-provenance and SBOM attestations, and keyless Cosign signing and
verification. Independent verification confirmed that:

- the immutable commit tag resolves to the deployment digest above;
- both platform images carry the exact source revision and run as UID/GID
  `65532:65532`;
- GitHub attestation subjects match the deployment digest, repository, signed
  tag and publishing workflow;
- the Sigstore certificate identity and GitHub OIDC issuer match the publishing
  workflow, with Rekor transparency-log index `2566647732`;
- the amd64 image starts with a read-only root filesystem, all capabilities
  dropped and `no-new-privileges`, while `pip`, `setuptools` and `msgpack` are
  absent.

Only the accepted deployment digest may be consumed by OK-170. The rejected
`rc.1` digest remains explicitly excluded.

## Candidate procedure

After the implementation PR is merged and the merge revision is verified on
`main`, an authorized maintainer creates a signed annotated tag:

```bash
git tag -s console-observer-dev-v0.1.0-rc.N \
  -m 'OpenKubes observed-state producer development candidate 0.1.0-rc.N'
git push origin console-observer-dev-v0.1.0-rc.N
```

Record the exact tag, source revision, workflow run and resulting digest in
OK-171. A tag is only for discovery; every OK-170 manifest and verification
must use `ghcr.io/openkubes/observed-state-producer@sha256:<digest>`.

Verify the resulting evidence:

```bash
gh attestation verify \
  'oci://ghcr.io/openkubes/observed-state-producer@sha256:<digest>' \
  --repo openkubes/openkubes

cosign verify \
  --certificate-identity \
  'https://github.com/openkubes/openkubes/.github/workflows/publish-console-observed-state-producer.yaml@refs/tags/console-observer-dev-v0.1.0-rc.N' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
  'ghcr.io/openkubes/observed-state-producer@sha256:<digest>'
```

Publication is a development candidate only. It does not deploy the producer,
provide CRDs, issue workload certificates, or claim production readiness.
