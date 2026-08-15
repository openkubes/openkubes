# OK-141 default API audience diagnostic closure v1

The one-shot diagnostic requested a ten-minute service-account token without an
explicit audience. The disposable workload API accepted that token for the exact
`Namespace/ok-observability` probe.

The returned default audience did not match the audience previously assigned by
the Runtime Binding. This positively identifies the guessed audience as the
cause of the Argo registration authentication failure.

No credential payload, Kubeconfig, CA data, endpoint or raw API response is
published. The diagnostic created no persistent API object and did not resume
the Happy Run.
