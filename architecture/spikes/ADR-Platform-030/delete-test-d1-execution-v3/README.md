# OK-141 delete D1 execution v3

Status: **OFFLINE PREPARED / BLOCKED / NO-GO**

The first authorized v2 execution stopped before any delete because the first
Argo Application advanced its `resourceVersion` after the read-only preflight.
Its name, namespace and UID still matched, and it had neither a deletion
timestamp nor a finalizer.

V3 keeps the preflight UID as the immutable identity anchor. Immediately before
each delete it performs the exact GET already required by the protocol, requires
the same name, namespace and UID, and uses the freshly observed
`resourceVersion` together with that UID as the delete preconditions. A change
between that GET and DELETE still fails closed in the API server.

No v1/v2 identity or stopped evidence is reinterpreted. This checkpoint grants
no delete authority.

```bash
python3 bounded_delete_d1_v3.py verify --candidate delete-d1-execution-candidate-v3.yaml
python3 test_bounded_delete_d1_v3.py -v
```
