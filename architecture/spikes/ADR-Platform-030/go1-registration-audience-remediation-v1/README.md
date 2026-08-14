# OK-141 registration audience remediation v1

The default-audience diagnostic proved that the disposable Kubernetes API
accepts a server-default service-account audience and rejects the audience that
the earlier Runtime Binding guessed.

This candidate performs one optimistic-concurrency-protected replacement of the
existing Argo cluster Secret. It first obtains a three-hour token without an
explicit audience and proves that token with the exact target Namespace GET.
The replacement retains the existing Secret identity and all non-credential
fields, changes only the bearer token and token-expiration annotation, and is
bound to the immediately observed UID and resourceVersion.

Updating the registration credential can immediately wake Argo reconciliation.
That side effect is explicit. No retry, rollback, cleanup, capability test or
failure injection is part of this candidate.
