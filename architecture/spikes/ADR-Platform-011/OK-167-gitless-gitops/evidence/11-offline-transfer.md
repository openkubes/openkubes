# 11 — Offline transfer of GitOps artifacts

> Historical record from 2026-10-29. Review findings and the 2026-10-30 retest are documented in [12-review-remediation.md](12-review-remediation.md). Original observations below are retained; they do not certify the revised implementation.

- Test IDs: Phase 9
- Date (UTC): 2026-10-29T12:45Z – 12:48Z
- Environment: oras 1.3.6, cosign v3.1.4, zot v2.1.20, Argo CD v3.5.6
- Relates to: ADR-028 §4.6 (referrer relationships must survive transfer) and §4.9 (offline
  portability); ADR-017 (which defines **no** `air-gapped` envelope)

## Steps and results

```sh
# 1. export, recursively, into an OCI layout — the "sneakernet" artifact
oras cp -r <reg>/<repo>@<digest> --to-oci-layout .local/offline/layout:imported \
  --from-ca-file … --from-registry-config …

# 2. re-import into a different repository
oras cp -r --from-oci-layout .local/offline/layout@<digest> <reg>/<imported-repo>:imported \
  --to-ca-file … --to-registry-config …
```

| Check | Result |
|---|---|
| Export produced a self-contained layout | 5 blobs, 28 KB, index lists the artifact **and** the signature manifest |
| Referrer present in the layout | `application/vnd.dev.sigstore.bundle.v0.3+json` |
| Digest after the round trip | `sha256:b4eb3ab95b73…` — **byte-identical to the original** |
| Referrer present after import | yes, same digest `sha256:341727bd8544…` |
| `cosign verify` against the imported copy | **succeeds** |
| Argo CD Application on the imported repository, digest-pinned | **Synced / Healthy**, 2 resources |
| Credentials for the imported repository | none created — the Q1.b prefix template covered it |

**Criterion K4 is met.** A GitOps artifact, its signature, and its verifiability all survive a
round trip through a file-system layout, and Argo CD deploys the imported copy unchanged.

## The finding that matters: legacy signatures are silently lost

The legacy-format signature from Q4.d is **not a referrer** — it is a tag. `oras cp -r` therefore
does not carry it:

| Step | Observation |
|---|---|
| `oras discover` on the legacy-signed artifact | **no referrers** |
| `oras cp -r` the artifact to a new repository | succeeds, digest identical |
| tags in the destination | only `imported` — **no `.sig` tag** |
| `cosign verify` against the copy | **`Error: no signatures found`** |
| copy `sha256-<digest>.sig` explicitly, then verify | **succeeds** |

The artifact copies cleanly and verification fails afterwards, with nothing in the copy step
reporting a problem. For an air-gap procedure this is the worst shape a defect can take: the
export looks successful.

This bears directly on **ADR-028 §4.6**, which requires that "migration, backup/restore, and
offline transfer MUST preserve these subject→referrer relationships". A legacy cosign signature
is not a referrer relationship at all, so the contract clause does not protect it. Two
consequences:

1. **Prefer the OCI 1.1 bundle format for anything that must travel.** It is a referrer and it
   survives.
2. **But zot only verifies the legacy format** (Q4.d). The two pull in opposite directions:
   the format that transfers is the one zot cannot check, and the format zot checks is the one
   that does not transfer. Any procedure has to pick one and state which, or carry both.

## Verdict

**PASS.** Offline transfer preserves digest, referrers and verifiability, and Argo CD syncs the
imported artifact. The legacy-signature gap is documented with its workaround.

## What this proves / What this does not prove

| Proves | Does not prove |
|---|---|
| An artifact and its bundle-format signature survive an OCI-layout round trip with an identical digest | That a large or multi-artifact export behaves the same — one artifact of 28 KB was moved |
| `cosign verify` succeeds against the imported copy | That verification happens anywhere in the deployment path — Q4.e shows it does not |
| Argo CD syncs from the imported repository, digest-pinned | That a cluster could pull the **workload images** offline — explicitly out of scope; podinfo still comes from ghcr.io |
| Legacy `.sig` signatures are dropped by `oras cp -r` and the loss is silent | That other tools drop them too, or that `oras` intends to |
| The Q1.b credential template covers a newly created repository under the prefix | That this scales to many prefixes or to credential rotation mid-transfer |
| **Nothing here establishes an air-gapped Constraint Envelope.** ADR-017 defines none, and ADR-028 §4.9 says explicitly that an offline-transfer proof does not create one. | That OpenKubes can operate air-gapped — this moved one artifact between two repositories on one host |
