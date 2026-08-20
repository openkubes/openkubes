# OK-141 delete D1-v2 preflight closure

Status: **PASS / PRIVATE DELETE TARGETS BOUND / REDACTED / NO-GO**

The normalized D1-v2 preflight completed six exact GETs against `ok-shared`
and bound five delete targets. All three Applications matched the authoritative
platform fixture under `argocd-application-c14n/v1`; the only normalized
default is an omitted `spec.source.directory.recurse=false`.

The first v2 attempt stopped fail-closed because the short-lived Argo target
token had expired. A bounded token refresh restored the existing registration
Secret with optimistic concurrency, a fresh D0-v3 snapshot rebound current
metadata, and one diagnosis-based D1-v2 run then passed. The D1 preflight
itself performed no mutation or delete.

Private runtime bindings and raw execution evidence remain under
`/private/tmp` with mode `0600`. This checkpoint contains only digests,
aggregate results, execution boundaries and redaction claims. It contains no
raw object, UID, ResourceVersion, endpoint, credential, Secret value, token or
kubeconfig content.

The five-minute D1 binding does not authorize deletion. D1 delete, D2, D3,
cleanup, outage and failure injection remain NO-GO.

Offline verification:

```bash
cd architecture/spikes/ADR-Platform-030/delete-test-d1-preflight-v2-closure
python3 verify_delete_d1_preflight_v2_closure.py --closure delete-d1-preflight-v2-closure-evidence.yaml
python3 test_delete_d1_preflight_v2_closure.py -v
```
