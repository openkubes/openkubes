# OK-141 registration integrity diagnostic v1

The Platform cause diagnostic narrowed all three Argo failures to the common
`TARGET-CONNECTION + CACHE` domain. This candidate checks the smallest next
boundary: whether the existing project-scoped Argo registration is internally
consistent with the private Runtime Binding and whether its static TokenRequest
credential can perform one exact target Namespace GET from the bounded executor.

The registration Secret and token are used only in memory. A temporary 0600
Kubeconfig is created only after every registration and token check passes and
is removed in all cases. Evidence contains only booleans, digests and bounded
timing metadata. This does not prove connectivity from inside `ok-shared`; that
remains a separate possible diagnostic if registration passes.
