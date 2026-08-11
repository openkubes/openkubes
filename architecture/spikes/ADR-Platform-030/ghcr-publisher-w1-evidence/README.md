# OK-141 publisher W1 deployment evidence

Status: **W1 complete and observed; P1 retry not authorized**

PR #128 deployed the exact relative-path publisher source to `main` without
dispatching it. The workflow remains manual-only, keeps workflow ID
`332090718`, and has the reviewed digest:

```text
sha256:6837271e8929eac133d1f5f6fb1bbaba3b83f61a772f27a856b51e79d673a27b
```

The post-merge workflow history contains only the historical failed P0 run
`31517187028`; no run was created by the W1 source deployment.

W1 proves only that the corrected workflow source is active and inert. It does
not reopen the exhausted smoke-run budget and does not authorize a publisher
retry, package write, attestation, GO-1, infrastructure access or failure
injection.
