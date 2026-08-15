# OK-141 first M0a v2 runtime evidence

Status: **STOP-NOT-SUCCESS; no retained CAAPH or bootstrap objects**

The authorized one-run v2 candidate passed its read-only preflight and created
the five temporary bootstrap objects. It stopped before CAAPH submission when
the negative authorization probe reported that `create serviceaccounts/token`
was allowed. The run and all three grants are consumed and cannot be retried.

The stop does not prove that the temporary principal could create a TokenRequest.
The executor passed `serviceaccounts/token` as the positional `TYPE/NAME`
argument to `kubectl auth can-i`. The bound kubectl v1.26.1 client documents
subresources separately through `--subresource`; the observed `yes` therefore
matched creation of a ServiceAccount named `token`, which the reviewed role
allowed. A corrected future probe must address resource `serviceaccounts` with
`--subresource=token` and must receive a new candidate and new grants.

Cleanup removed all five temporary objects. The post-failure preflight proves
that the CAAPH Namespace, both CAAPH CRDs, all reviewed installation objects,
and all CAPI lifecycle objects are absent. HCP/HRP submission and target
convergence were never reached.

The bounded 90-second token-rejection observation also remained false. No
token or temporary kubeconfig was retained; expiry at
`2026-08-12T12:50:57Z` remained the hard exposure bound. This evidence makes
no immediate-revocation claim.

At capture time this directory was local preparation only and granted no
publication. A later explicit publication grant may publish this reviewed,
redacted checkpoint; it does not alter the runtime authorization record and
grants no retry, cleanup, rollback, M0b-I, GO-1, target convergence, or failure
injection.

Verify with:

```bash
python3 verify_m0a_v2_first_run.py \
  --evidence m0a-v2-first-run-evidence-v1.yaml \
  --digest-file m0a-v2-first-run-evidence-v1.sha256
pytest -q tests
```
