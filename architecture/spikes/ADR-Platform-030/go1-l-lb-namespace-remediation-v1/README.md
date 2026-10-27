# OK-141 CAPK load-balancer namespace remediation v1

Status: **OFFLINE-PROVEN / BLOCKED / NO-GO**

The accepted G1 submission created and bootstrapped both Talos VMs, but CAPK
resolved the external infrastructure kubeconfig's current-context namespace as
`ok-obs-verify`. Consequently, `Service/ok-obs-verify/disposable-ok141-lb`
received the bound VIP `192.168.100.213` while its selector could not reach the
control-plane VMI in namespace `disposable-ok141`. The Service has no endpoints;
the management-plane remote connection probe therefore fails.

The source renderer is already fixed in `openkubes/ok-cluster` commit
`38cfe626b328e99f07194ee254ec69b19fca1064`. That fix does not mutate the
preserved run. This candidate repairs only that run:

1. normalize only the provider kubeconfig current-context namespace in the
   existing management Secret;
2. create the exact target Service while requesting the already bound VIP;
3. re-read and delete only the misplaced Service;
4. wait for the target Service to hold the same VIP and non-empty Endpoints;
5. clear only the provider-derived KubevirtCluster endpoint host with JSON Patch
   UID/resourceVersion/value tests, causing CAPK to re-evaluate it; and
6. observe exact endpoint objects without resuming the Happy Run.

The target Service is created before the old Service is deleted. It may remain
Pending briefly because MetalLB does not assign one address to both Services.
After the old Service is deleted, the target requests `192.168.100.213`
explicitly. Preserving that VIP matters because Talos was already bootstrapped
against it.

The operation is non-atomic. `kubectl delete --raw` cannot carry a server-side
UID/resourceVersion deletion precondition, so the tool performs an exact
UID/resourceVersion re-read immediately before its one permitted delete. A
failure stops and preserves partial state. There is no retry, rollback, general
cleanup, Happy-Run resume, G3, platform convergence, evidence publication, or
failure injection authority.

Passing offline tests does not grant cluster contact or mutation. Execution
requires a new, active, single-run grant binding this exact candidate digest and
explicitly accepting the DEV rebuild-on-failure boundary.
