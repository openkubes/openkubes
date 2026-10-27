# OK-141 capability runtime v2

This directory binds and records the first successful corrected v9 capability
run against the existing disposable cluster.

The run uses the merged `ok-observability` source revision and corrected,
bounded synthetic-resource naming. It does not reuse either historical failed
v8 capability execution. The public closure contains only redacted state and
digests; all raw runtime evidence remains under `/private/tmp`.

Result:

- all three Applications were current, `Synced`, and `Healthy`;
- the exact capability test exited successfully with firing-only alert acceptance;
- four known synthetic resources were confirmed absent after cleanup; and
- temporary kubeconfig, tool directory, and port-forward logs were removed.

This proves the OK-141 happy path. It does not grant or claim execution of
management-outage, executor-restart, delete/finalizer, break-glass, or other
failure-injection scenarios.
