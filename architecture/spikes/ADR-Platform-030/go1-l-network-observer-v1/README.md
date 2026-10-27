# OK-141 GO1-L enablement and NetworkReady observer v1

This checkpoint defines the bounded observation path after the reviewed Cilium
`HelmChartProxy` submission.

The observer correlates the exact HCP, exactly one controller-generated HRP,
the CAPI Cluster, and the standard CAPI workload kubeconfig Secret. It writes
the workload kubeconfig only to an exclusive `0600` file under `/private/tmp`,
uses the verified Kubernetes v1.36.2 client, and removes the ephemeral file on
every exit path.

Workload evidence requires two current Nodes, current Cilium and Envoy
DaemonSets, the current Cilium operator Deployment, exact pinned images, and
`Ready=True` plus `NetworkUnavailable=False/CiliumIsUp` on both Nodes. The
profile's functional probe is implemented by one hard-coded Pod exec into one
selected Cilium agent:

```text
cilium-health status --probe --output json
```

The synchronous response must contain successful HTTP and ICMP host and health
endpoint paths for exactly the two current Nodes. The command and parsing
semantics are bound to Cilium v1.19.6 source commit
`9a8982433e18019e290b8199c0c4ad24f66befe8`.

This is not a generic exec endpoint. The tool accepts no command argument, and
the grant must explicitly authorize the fixed Pod exec subresource call and
the exact workload-kubeconfig Secret read. No Secret, kubeconfig, token, key,
certificate payload, full API object, IP address, or probe raw output is
retained.

The candidate is offline-only and grants no cluster contact or mutation.
