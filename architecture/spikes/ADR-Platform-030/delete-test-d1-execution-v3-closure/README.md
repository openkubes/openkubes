# OK-141 delete D1 v3 closure

Status: **PASS / GITOPS TARGET QUIESCED / D2-D3 NO-GO**

The bounded D1-v3 run deleted exactly the three disposable Applications, the
registration Secret and the disposable AppProject on `ok-shared`. Every delete
used the preflight UID and the immediately observed live `resourceVersion` as
API preconditions. No retry, force delete, finalizer mutation, rollback or
general cleanup occurred.

The disposable CAPI cluster, VMs, PVs and retained storage were not deleted.
