# OK-141 first M0a v3 runtime evidence

Status: **STOP-NOT-SUCCESS; no retained CAAPH or bootstrap objects**

The authorized one-run v3 candidate passed preflight and every positive and
negative authorization/admission probe. In particular, the corrected
`serviceaccounts --subresource=token` review returned `deny` for the temporary
installer.

The run stopped when the bound 19-object server-side apply exited non-zero.
No reviewed CAAPH object materialized. The most likely cause is deliberately
classified as high-confidence inference rather than response-proven fact: the
executor invoked server-side apply, whose request form is PATCH, while the v3
installer role deliberately denied `patch`. The raw subprocess failure did not
retain the API response body.

Cleanup removed all five temporary bootstrap objects. A complete read-only
post-failure preflight proves that the CAAPH Namespace, both CAAPH CRDs, all
reviewed installation objects, and all CAPI lifecycle objects are absent.
HCP/HRP submission and target convergence were never reached, so no rollback
is needed or authorized.

The expiry-bound credential check also stopped unsuccessful: the exact token
still authenticated at `expirationTimestamp + 30s`. No token or temporary
kubeconfig was retained. The evidence makes no claim that expiry-based API
rejection was proven.

At capture time this directory was local preparation only and granted no
publication. A later explicit grant permits publication of this exact reviewed
and redacted checkpoint while the raw local evidence remains excluded. That
grant does not alter the runtime authorization record and grants no retry,
cleanup, rollback, M0b-I, GO-1, target convergence, or failure injection.

Verify with:

```bash
python3 verify_m0a_v3_first_run.py \
  --evidence m0a-v3-first-run-evidence-v1.yaml \
  --digest-file m0a-v3-first-run-evidence-v1.sha256
pytest -q tests
```
