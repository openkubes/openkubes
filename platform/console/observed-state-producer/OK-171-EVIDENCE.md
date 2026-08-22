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

## Candidate procedure

After the implementation PR is merged and the merge revision is verified on
`main`, an authorized maintainer creates a signed annotated tag:

```bash
git tag -s console-observer-dev-v0.1.0-rc.1 \
  -m 'OpenKubes observed-state producer development candidate 0.1.0-rc.1'
git push origin console-observer-dev-v0.1.0-rc.1
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
  'https://github.com/openkubes/openkubes/.github/workflows/publish-console-observed-state-producer.yaml@refs/tags/console-observer-dev-v0.1.0-rc.1' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
  'ghcr.io/openkubes/observed-state-producer@sha256:<digest>'
```

Publication is a development candidate only. It does not deploy the producer,
provide CRDs, issue workload certificates, or claim production readiness.
