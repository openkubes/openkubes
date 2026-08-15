# OK-141 GO1-L lifecycle/API observer v1

This checkpoint defines the bounded read-only bridge between lifecycle stage
`G1` and Cilium submission stage `G3`.

The observer performs only four exact raw GETs against `ok-mgmt`. It does not
use discovery, list, watch, a workload kubeconfig, or any mutation. It waits for
the CAPI `Cluster` to report a current-generation
`ControlPlaneInitialized=True`, while correlating the exact Cluster,
KubevirtCluster, TalosControlPlane, and MachineDeployment identities to intent
revision `R`.

`ControlPlaneInitialized` is deliberately used instead of Node readiness. The
selected CAAPH bootstrap path must install Cilium before workload Nodes can be
expected to become Ready.

The emitted evidence is redacted structural evidence. It retains UIDs,
generations, typed references, endpoint presence, and selected condition fields;
it never retains kubeconfig bytes, Secrets, tokens, keys, or full API objects.

This merged candidate grants no cluster contact and no authority. A current,
single-run read-only grant derived under the later exact Happy-Run grant is
required before execution.
