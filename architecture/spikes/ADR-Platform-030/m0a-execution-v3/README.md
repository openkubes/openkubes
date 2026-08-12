# OK-141 M0a v3 security-boundary candidate

Status: **BLOCKED / offline only / no authority**

This amendment responds to the consumed first M0a-v2 run. The v2 executor
stopped before CAAPH submission because its negative TokenRequest authorization
probe used `serviceaccounts/token` as the positional `TYPE/NAME` argument to
kubectl v1.26.1. That syntax asks about a ServiceAccount named `token`; it does
not address the `token` subresource.

The v3 boundary requires the unambiguous form:

```bash
kubectl auth can-i create serviceaccounts \
  --subresource=token \
  --namespace=openkubes-system
```

The expected result for the temporary installer is `no`. The administrator
continues to create the one bounded TokenRequest; the installer receives no
TokenRequest permission.

The v2 run also confirmed that deleting the temporary ServiceAccount and RBAC
does not guarantee authentication rejection within 90 seconds. V3 therefore
does not use that arbitrary interval as its success boundary. It retains the
at-most-ten-minute token lifetime and observes until the API rejects the token
or until the bound expiration timestamp plus 30 seconds. A missing rejection
after that deadline remains `STOP-NOT-SUCCESS`; immediate revocation is never
claimed.

This changes the previously accepted revocation-observation behavior. The
included risk-acceptance candidate must receive a new explicit acceptance
before any executable v3 candidate or grant can exist.

## Executable candidate

The risk was explicitly accepted and is recorded in
`../m0a-v3-risk-acceptance/m0a-v3-risk-acceptance-v1.yaml`. The additive
`m0a-execution-candidate-v3.yaml` now binds that record, the corrected
authorization-probe helper, the unchanged 19-object CAAPH payload, and
`controlled_m0a_execution_v3.py`.

The executor keeps the v2 bootstrap manifests and their exact identities. It
changes only the control logic required by the v3 boundary: the installer is
checked against the real `serviceaccounts/token` subresource, and credential
rejection is observed through the bound expiration timestamp plus 30 seconds.

`m0a-combined-grant-v3.template.yaml` is deliberately `NO-GO`. The executable
candidate still requires a fresh read-only live preflight and three new,
distinct, exact grants before one run can be considered. Neither the risk
acceptance nor this checkpoint grants a retry.

This checkpoint authorizes no credential, admission object, CAAPH installation,
retry, rollback, publication, M0b-I, GO-1, target convergence, or failure
injection.

Verify with:

```bash
python3 verify_m0a_v3_security_boundary.py \
  --candidate m0a-v3-security-boundary.yaml \
  --digest-file m0a-v3-security-boundary.sha256
python3 controlled_m0a_execution_v3.py verify \
  --candidate m0a-execution-candidate-v3.yaml
pytest -q tests
```
