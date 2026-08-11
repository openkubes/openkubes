# OK-141 P1 publication evidence

Status: **publication objective verified; workflow conclusion failed; no retry**

The single P1 run published the deterministic transport, created the GitHub
artifact attestation and pulled the OCI artifact back by digest. The final step
then failed before creating its receipt because `gh attestation verify` had no
`GH_TOKEN` environment variable.

This checkpoint does not relabel the Actions run as successful. It preserves
both truths:

```text
GitHub Actions run conclusion
  -> failure

Publication objective
  -> OCI push successful
  -> attestation successful
  -> digest pull-back successful
  -> independently re-pulled and verified after the run
```

Independent read-only verification proved:

- public tag and digest both resolve to manifest
  `sha256:c9bdeadf1ee859c69ed0ab1136ec6b590139fe931eff44039265c144cea76dc8`;
- pulled transport digest is
  `sha256:1c419e42d8403073e6b7d93ae4829f3559b940d70365791b97a373e7a4ce6f05`;
- embedded correlation identifies the exact successful C1 run, workflow,
  source SHA, original bundle protocol and internal bundle digest;
- GitHub's attestation verifier accepts the exact manifest subject, signer
  workflow, `main` ref and source commit;
- the existing receipt verifier returns
  `VERIFIED-PULL-BACK-WITH-SOURCE-CORRELATION`.

The P1 run budget is consumed. No rerun is authorized. The missing-token defect
must be corrected separately for future workflow health, without recreating the
already published artifact or attestation.

No cluster credential, secret or private material is retained here. GO-1,
infrastructure mutation and failure injection remain NO-GO.
