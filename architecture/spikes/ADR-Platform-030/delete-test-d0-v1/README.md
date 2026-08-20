# OK-141 delete D0 private binding preparation v1

Status: **OFFLINE-PREPARED / READ-ONLY GRANT REQUIRED / NO-GO**

D0 prepares a fresh private snapshot for only the first delete segment:

```text
D1 Argo quiescence
        ↓
D2 CAAPH close
        ↓
D3 authoritative CAPI Cluster delete
```

It does not authorize or perform any of those stages. It also cannot authorize
later retained-PV or Longhorn cleanup: D5 requires a new post-controller-closure
binding because the PV phases, Longhorn attachment states, UIDs and resource
versions will have changed.

The candidate defines 36 exact or explicitly post-filtered GETs across
`ok-shared`, `ok-mgmt`, `ok-infra` and the disposable workload. Secret GETs are
classified separately: only metadata and sorted data-key names may enter the
private binding; values are discarded in memory and never logged.

Successful execution would create exactly two absent-before-run files with mode
`0600`:

```text
/private/tmp/ok141-delete-d0-runtime-binding-v1.json
/private/tmp/ok141-delete-d0-evidence-v1.json
```

The binding expires after ten minutes. A consumed, expired, changed or partially
written binding fails closed. The public grant file and publication candidate are
non-authorizing templates.

Offline verification:

```bash
python3 architecture/spikes/ADR-Platform-030/delete-test-d0-v1/prepare_delete_d0_binding_v1.py \
  verify \
  --candidate architecture/spikes/ADR-Platform-030/delete-test-d0-v1/delete-d0-binding-candidate-v1.yaml

python3 architecture/spikes/ADR-Platform-030/delete-test-d0-v1/test_prepare_delete_d0_binding_v1.py -v
```

No cluster contact occurs during these commands.
