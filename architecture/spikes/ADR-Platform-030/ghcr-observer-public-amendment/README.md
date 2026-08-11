# OK-141 public GHCR observer amendment

Status: **implemented offline; inert; not deployed**

P1 proved that `ghcr.io/openkubes/ok141-evidence` is publicly readable by
manifest digest. The historical observer prototype intentionally expected a
private package and rejected unauthenticated success. That assumption no
longer matches the accepted OK-141 evidence boundary.

This additive v2 candidate:

- performs one anonymous `HEAD` by exact OCI manifest digest;
- accepts only an exact `Docker-Content-Digest` match;
- maps `401`/`403` to `PackageReadDenied`, `404` to `DigestMissing`, and other
  registry failures to `EvidenceUnverifiable`;
- requires only `contents: read` for checkout;
- exposes no credential, write, delete, restore, republish, issue or webhook
  surface;
- retains the existing fail-closed evaluator, retention check and job summary.

The candidate remains outside `.github/workflows`. No workflow or schedule is
deployed, and no observation run is authorized by this checkpoint.
