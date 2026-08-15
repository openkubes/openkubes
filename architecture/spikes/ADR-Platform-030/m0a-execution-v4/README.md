# OK-141 M0a v4 security-boundary candidate

Status: **BLOCKED / offline only / no authority**

The consumed M0a-v3 run proved the corrected TokenRequest authorization
boundary and stopped without retaining any CAAPH object. It also exposed two
independent defects in the executable method:

1. `kubectl apply --server-side` uses the Kubernetes apply PATCH media type,
   while the deliberately bounded installer role permits only `create` and
   `get`.
2. Kubernetes v1.34.1 accepts JWT expiry with a one-minute default leeway and
   wraps successful token authentication with a ten-second cache by default.
   Observing at `expirationTimestamp + 30s` was therefore too early.

`m0a-v4-upstream-semantics.yaml` records the exact upstream tag, commit, source
paths, and source-file digests supporting these conclusions. The v4 candidate
changes no CAAPH payload, RBAC, or admission identity. It proposes:

- one create-only submission of the exact reviewed 19-object stream after all
  19 identities have been proven absent;
- no patch, update, delete, list, or watch permission for the installer;
- fail-closed observation of the exact temporary credential until rejection or
  `expirationTimestamp + 100s` (60s JWT leeway + 10s successful-authentication
  cache + 30s observation/clock tolerance).

Create is intentionally treated as a one-shot bootstrap operation, not as a
reconciliation mechanism. It is non-idempotent, does not establish apply field
ownership, and may leave a prefix of the 19-object stream materialized if a
later create fails. Such partial state is `STOP-NOT-SUCCESS` and requires a
separately reviewed rollback decision; automatic rollback remains forbidden.

The included risk-acceptance candidate is not an acceptance and grants no
authority. The consumed v1-v3 grants cannot be reused. A new explicit risk
acceptance is required before an executable v4 candidate may be prepared, and
that later candidate requires new exact grants before any cluster contact or
mutation.

## Executable candidate

The risk was explicitly accepted and is recorded in
`../m0a-v4-risk-acceptance/m0a-v4-risk-acceptance-v1.yaml`. The additive
`m0a-execution-candidate-v4.yaml` binds that record, the primary-source
semantics evidence, the unchanged admission/RBAC and 19-object payload, and
`controlled_m0a_execution_v4.py`.

The executor uses one `kubectl create -f -` submission. It records the exact
19-object inventory even when creation fails, preserves any partial CAAPH state
for a separate decision, and never performs automatic retry or rollback. Raw
runtime evidence must be written to one previously absent path below
`/private/tmp` bound by the future grant. Token rejection is observed through
the bound expiry-plus-100-second deadline.

`m0a-combined-grant-v4.template.yaml` is deliberately `NO-GO`. The executable
candidate still requires a fresh read-only live preflight and three new,
distinct, exact grants before one run can be considered. Neither the accepted
risk nor this checkpoint grants a retry.

`m0a-combined-grant-v4.yaml` records the later three explicit grants for
candidate `sha256:3fc1fee9…db7da8`. It authorizes exactly one combined run in
the recorded UTC window, binds raw evidence to one path below `/private/tmp`,
and leaves HCP/HRP submission, Cilium convergence, retry, CAAPH rollback,
evidence publication, M0b-I, GO-1, target convergence, and failure injection
excluded.

Verify with:

```bash
python3 verify_m0a_v4_upstream_semantics.py \
  --evidence m0a-v4-upstream-semantics.yaml \
  --digest-file m0a-v4-upstream-semantics.sha256
python3 verify_m0a_v4_security_boundary.py \
  --candidate m0a-v4-security-boundary.yaml \
  --digest-file m0a-v4-security-boundary.sha256
python3 verify_m0a_v4_risk_candidate.py \
  --candidate m0a-v4-risk-acceptance-candidate.yaml \
  --digest-file m0a-v4-risk-acceptance-candidate.sha256
python3 controlled_m0a_execution_v4.py verify \
  --candidate m0a-execution-candidate-v4.yaml
pytest -q tests
```
