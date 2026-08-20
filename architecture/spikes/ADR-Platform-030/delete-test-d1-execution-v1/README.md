# OK-141 delete D1 execution candidate

Status: **OFFLINE PREPARED / BLOCKED / NO-GO**

This checkpoint prepares only D1: quiescing the disposable GitOps target
binding on `ok-shared`. The runner accepts a fresh private D1-v2 binding and a
separate single-use destructive grant. It then deletes exactly five resources
in the protocol order:

1. Dashboards Application
2. Alerting Application
3. Core Application
4. disposable target registration Secret
5. disposable AppProject

Every deletion is preceded by an exact GET and requires the UID and
ResourceVersion from the private binding. Applications must still have no
finalizer or deletion timestamp. Deletes use `DeleteOptions` preconditions and
background propagation; no target workload resource is directly deleted.

The runner stops on the first error and preserves partial state. It has no
retry, rollback, force-delete, finalizer-edit or cleanup path. The private
binding expires after five minutes, so execution requires a new D0 plus D1-v2
preflight immediately before a separately authorized D1 run.

This checkpoint does not authorize D1 or any later stage.

Offline verification:

```bash
cd architecture/spikes/ADR-Platform-030/delete-test-d1-execution-v1
python3 bounded_delete_d1_v1.py verify --candidate delete-d1-execution-candidate-v1.yaml
python3 test_bounded_delete_d1_v1.py -v
```
