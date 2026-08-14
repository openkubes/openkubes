# OK-141 target-access cause diagnostic v1

The Registration Integrity diagnostic proved that the Argo registration,
Runtime Binding, CA, TokenRequest subject, audience and expiry all match. The
same token nevertheless failed one exact `Namespace/ok-observability` GET from
the bounded executor.

This candidate repeats only that bound read path and classifies the response in
memory as success, target connection, DNS, TLS, authentication, authorization,
not found or unknown. It retains no registration Secret, token, CA, endpoint,
raw response or Kubeconfig. It does not resume the Happy Run or mutate either
cluster.
