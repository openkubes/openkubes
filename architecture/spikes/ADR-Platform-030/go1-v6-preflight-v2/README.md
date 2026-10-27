# OK-141 GO-1 v6 preflight v2

Preflight v2 is an additive transport correction to v1. The v1 query and
acceptance contract remains authoritative, but v2 replaces the unbound
`kubectl` lookup with the exact locally verified v1.34.1 client.

It also binds the three redacted credential identities produced by C0-V6.
The raw credential-identity evidence remains local and unpublished.

```text
kubectl:             /private/tmp/ok141-kubectl-v1.34.1-darwin-amd64
kubectl digest:      sha256:bb211f2b...cefcfdf
Query contract:      v1, unchanged
Credential IDs:      C0-V6 complete locally
Live preflight:      NOT GRANTED / NOT-RUN
Mutation:            NO-GO
GO1-L / GO-1:        NOT GRANTED
```
