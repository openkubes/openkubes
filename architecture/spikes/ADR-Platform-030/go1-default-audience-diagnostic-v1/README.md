# OK-141 default API audience diagnostic v1

The Target-Access cause diagnostic classified the bound service-account token
failure as `AUTHENTICATION`. Earlier M0b evidence had explicitly left the exact
target API audience unobserved, but the later Runtime Binding assigned
`https://kubernetes.default.svc.cluster.local` without an execution proof.

This candidate requests exactly one ten-minute token without an explicit
audience, which lets the Kubernetes API server select its configured default API
audience. It then performs one exact `Namespace/ok-observability` GET. Success
proves that the old explicit audience was the causal mismatch. The token,
Kubeconfigs, CA, endpoint and raw responses remain private and ephemeral.

This is a transient TokenRequest diagnostic, not a Happy-Run retry and not a
persistent cluster mutation.
