# OK-141 provider-access materializer v1

Status: **OFFLINE-PROVEN-BLOCKED-NO-GO**

This checkpoint defines the separate dynamic step between management Namespace
creation and CAPI lifecycle submission. The materializer reads exactly the
bound local `ok-infra` kubeconfig and constructs exactly one Secret for CAPK on
`ok-mgmt`.

```text
local ok-infra kubeconfig (read-only, mode 0600)
        ↓ transient process memory only
exact Secret/data.kubeconfig
        ↓ fixed kubectl create -f - using separate ok-mgmt credential
ok-mgmt/disposable-ok141/external-infra-kubeconfig-disposable-ok141
```

Credential and Secret bytes are forbidden from Git, command arguments,
environment variables, logs, retained Evidence, public content digests, and
the tool result. The generated JSON exists only in process memory and the
captured subprocess stdin. The submitter remains responsible only for static
objects; this tool cannot accept arbitrary paths, Secret identities, data keys,
commands, retry, rollback, update, patch, apply, or delete operations.

The merged candidate is inert. Runtime would still require two distinct
short-lived credential receipts, the accepted management-Namespace receipt,
an exact Secret-absence receipt, and one fresh digest-bound grant.

Verify offline:

```bash
python3 architecture/spikes/ADR-Platform-030/go1-l-provider-access-v1/verify_provider_access_materializer_v1.py
python3 architecture/spikes/ADR-Platform-030/go1-l-provider-access-v1/test_bounded_provider_access_materializer_v1.py -v
```

```text
Materializer mechanism:  offline proven
Credential bytes:        absent from repository/evidence
Credential use:          NOT GRANTED
Secret creation:         NOT GRANTED
Recreation:              NOT GRANTED
GO1-L:                   NOT GRANTED
GO-1:                    NOT GRANTED
Infrastructure:          NO-GO
Failure Injection:       NO-GO
```
