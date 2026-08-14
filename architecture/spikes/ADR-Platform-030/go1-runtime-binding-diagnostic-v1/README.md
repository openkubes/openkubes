# OK-141 runtime-binding diagnostic v1

Resume v6 proved `NetworkReady=True` and then stopped fail-closed because the
existing runtime-binding tool reported only `bounded raw GET failed`. The
runtime-binding boundary contains exactly three reads:

1. the workload Kubeconfig Secret on `ok-mgmt`;
2. `Namespace/kube-system` on the disposable workload cluster; and
3. `StorageClass/local-path` on that workload cluster.

The first two reads are expected to succeed because the immediately preceding
NetworkReady observer used the same workload credential and queried resources
in `kube-system`. The third read is the leading hypothesis: `ok-cluster`
installs `local-path-provisioner` through a separate `install-storage` step,
while the Happy Run has so far executed only lifecycle creation and Cilium
enablement.

This package does not treat that inference as fact. Its one-shot diagnostic
distinguishes the three exact reads and retains only per-stage result
categories, numeric exit codes, and stdout/stderr digests. It never retains a
Secret, Kubeconfig, API endpoint, object payload, UID, ResourceVersion, IP
address, or raw error text.

The diagnostic is read-only and requires a separate, current grant. It grants
no Happy Run continuation, storage installation, platform mutation, retry,
cleanup, publication, or failure injection.
