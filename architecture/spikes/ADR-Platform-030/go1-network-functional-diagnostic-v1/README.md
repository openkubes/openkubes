# OK-141 functional connectivity diagnostic v1

The corrected NetworkReady observation passed all desired-state, controller,
Node, rollout and image checks, but its one synchronous Cilium health probe
reported a failed path from the control-plane Node's host endpoint.

This candidate performs exactly one new read-only diagnostic probe against the
same UID-bound `cilium-agent` Pod. It obtains the workload kubeconfig from the
one existing CAPI Secret, materializes it only at a fixed `0600` path, verifies
the target identity, reads the exact Pod, executes the fixed command, and
removes the kubeconfig.

The output never retains raw probe output, status text, addresses, Secret data
or kubeconfig bytes. Each path records only Node name, section, protocol,
coarse status category, status digest and probe timestamp.

This is not a NetworkReady retry and cannot resume the Happy Run. It remains
`NO-GO` until a separate exact diagnostic grant is issued.
