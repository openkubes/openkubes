# OK-141 evidence collector offline prototype

Status: **implemented offline; inert; C0/C1/P0 remain NOT GRANTED**

The collector candidate deliberately has no Kubernetes credential and no
cluster network access. It accepts only an exact, already-reviewed evidence
intake commit reachable from `main`, under the fixed evidence path. The
run-bound bundle embeds the intake commit, path, and context digest before it
is uploaded as a seven-day Actions artifact named `ok141-evidence-bundle`.

This DEV mechanism trades repository-history retention for avoiding a
permanently privileged hosted or self-hosted runner. The bundle verifier still
rejects secrets, kubeconfigs, private keys, bearer headers, unsafe paths,
symlinks, and changed evidence.

A successful collector run remains only a P0 prerequisite. It cannot authorize
the active publisher.

```text
Collector workflow: absent / inert candidate only
C0 / C1 / P0:      NOT GRANTED
Cluster credential: none
Infrastructure:    unchanged
Failure Injection: NO-GO
```
