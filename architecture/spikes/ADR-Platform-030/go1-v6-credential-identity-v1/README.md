# OK-141 GO-1 v6 credential identity C0

GO-1 v6 needs three current, redacted API identities before its live read-only
preflight can be granted. This package derives those identities locally from
the fixed `ok-infra`, `ok-mgmt`, and `ok-shared` kubeconfig paths.

The inspection does not invoke `kubectl`, resolve DNS, open TCP connections,
or contact any cluster. It emits only the target plane, HTTPS API server, CA
fingerprint, and a digest of that redacted identity. Credential bytes, context
names, users, tokens, certificates, keys, passwords, and kubeconfig digests are
forbidden.

`verify` and `plan` remain offline. `run` requires a separate, current,
single-run C0 grant and writes only to the exclusive `0600` path bound by the
candidate.

```text
C0 candidate:       OFFLINE-PROVEN / NOT-RUN
Credential read:    NOT GRANTED
Cluster contact:    forbidden
Mutation:           NO-GO
GO1-L / GO-1:       NOT GRANTED
```
