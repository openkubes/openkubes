# OK-141 M0a v2 security-boundary candidate

Status: **BLOCKED / offline only / no authority**

This amendment responds to the consumed first M0a run. Kubernetes treats
Server-Side Apply of an absent object as `create`; the v1 credential exposed
only `get` and `patch`, so it could not materialize the reviewed CAAPH set.

The v2 model deliberately does not add `patch`:

1. preflight proves all 19 reviewed targets absent;
2. RBAC permits `create` only for the exact required resource types and `get`
   only for the exact reviewed names;
3. a fail-closed `ValidatingAdmissionPolicy` restricts the installer principal
   to the exact 19 `(group, resource, namespace, name)` tuples;
4. the digest-bound executor remains the payload-content control;
5. if a target appears after preflight, Server-Side Apply becomes `patch` and
   is rejected by RBAC.

The admission policy constrains identity, not complete object content. It does
not turn a digest annotation into proof. A later executable candidate must
still re-verify the exact reviewed payload immediately before submission.

Token revocation is also corrected. A TokenRequest token cannot be individually
revoked. The v2 design uses a maximum ten-minute token, deletes the temporary
ServiceAccount/RBAC after use, and polls for authentication rejection for up to
90 seconds. Failure to observe rejection is `STOP-NOT-SUCCESS`; expiry remains
the hard upper exposure bound. No claim of immediate revocation is made.

This checkpoint grants no credential creation, policy installation, CAAPH
installation, retry, rollback, publication, target convergence, GO-1, or
failure injection.

## Executable candidate

`m0a-execution-candidate-v2.yaml` binds the accepted security boundary to a
three-grant executor. The three independently named gates are temporary
credential bootstrap (`M0A-C1-v2`), temporary admission bootstrap
(`M0A-A1-v2`), and one CAAPH control-plane installation (`M0a-I-v2`). The
included grant file is a `NO-GO` template, not authority.

The read-only preflight in `m0a-v2-live-preflight-v1.yaml` passed against the
bound `ok-mgmt` identity. It is historical observation only; the executor must
repeat the same preflight inside any future authorized run.

Primary references:

- <https://kubernetes.io/docs/reference/using-api/api-concepts/#patch-and-update>
- <https://kubernetes.io/docs/reference/access-authn-authz/rbac/#referring-to-resources>
- <https://kubernetes.io/docs/reference/access-authn-authz/validating-admission-policy/>
- <https://kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin/#delete-invalidate-a-service-account-token>
