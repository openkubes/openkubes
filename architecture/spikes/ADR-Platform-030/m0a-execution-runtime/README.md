# OK-141 first M0a runtime evidence

Status: **STOP-NOT-SUCCESS; no retained CAAPH or credential objects**

The authorized one-run candidate passed its read-only preflight, created its
temporary credential, and stopped when the exact CAAPH server-side apply failed.
The run is consumed and cannot be retried.

Post-failure observation proves that the temporary ServiceAccount/RBAC, the
`caaph-system` Namespace, both CAAPH CRDs, all installation objects, and all
CAPI lifecycle objects are absent. No cleanup or automatic rollback occurred.

The immediate token-rejection check failed even after the ServiceAccount and
RBAC were deleted. No token or temporary kubeconfig was retained, and the token
was bounded to 60 minutes. This is recorded as a failed revocation claim, not
hidden by the later object-absence observation.

The likely apply cause is intentionally marked inferred: server-side apply of
an absent object appears to require `create`, while the temporary role exposed
only `get` and `patch`. A new candidate must solve that boundary and receive new
grants; this evidence grants no retry.

Verify the redacted artifact and its pinned digest with:

```bash
python3 verify_m0a_first_run.py \
  --evidence m0a-first-run-evidence-v1.yaml \
  --digest-file m0a-first-run-evidence-v1.sha256
pytest -q tests
```
