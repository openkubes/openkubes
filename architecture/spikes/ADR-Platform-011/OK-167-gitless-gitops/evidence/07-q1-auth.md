# 07 — Q1: authentication and trust

- Test IDs: Q1.a–Q1.g
- Date (UTC): 2026-10-29T12:09Z – 12:45Z
- Environment: Argo CD v3.5.6, zot v2.1.20

## Q1.a — exact repository Secret

Works (Phase 5/6). Shape, with no values:

```yaml
metadata:
  name: ok167-zot-podinfo-manifests
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository   # without this, Argo CD ignores the Secret
stringData:
  type: oci
  url: oci://zot.zot.svc.cluster.local:5000/openkubes/machine/gitops/podinfo-manifests
  username: gitops-puller                        # read-only identity
  password: <from secret store>
```

## Q1.b — credential template with a URL prefix — **works for `type: oci`**

A `repo-creds` Secret was created for the prefix
`oci://zot.zot.svc.cluster.local:5000/openkubes/machine/gitops`, and then the Kustomize
Application was created for `…/podinfo-kustomize`, for which **no exact repository Secret
exists**. Verified before the test that only `ok167-zot-podinfo-manifests` was present.

Result: `Synced` / `Healthy`, 2 resources. The same template later served the
`…/imported/podinfo-manifests` repository in Phase 9, again with no exact Secret.

**Prefix matching works for OCI repositories in v3.5.6.** Operationally this is the difference
between one credential per repository and one per prefix — it is what makes the Vault + VSO path
practical, because VSO then renders one Secret, not one per artifact stream.

## Q1.c — wrong password

The password in the repository Secret was replaced with a deliberately wrong value and the
repo-server restarted. The Application condition:

```text
[ComparisonError] Failed to load target state: failed to generate manifest for source 1 of 1:
rpc error: code = Unknown desc = failed to resolve revision "v1.1.0":
cannot get digest for revision v1.1.0:
HEAD "https://zot.zot.svc.cluster.local:5000/v2/openkubes/machine/gitops/podinfo-manifests/manifests/v1.1.0":
response status code 401: Unauthorized
```

Exemplary: it names the operation, the exact URL and the status code. Restoring the correct
password and restarting the repo-server returned the Application to `Synced` / `Healthy` with
no further intervention.

## Q1.d — remove the CA from `argocd-tls-certs-cm` — **it is what provides OCI trust**

A Helm upgrade without `--set-file` emptied the ConfigMap (`keys: EMPTY`). After a repo-server
restart:

```text
… Head "https://zot.zot.svc.cluster.local:5000/v2/…/manifests/v1.1.0":
tls: failed to verify certificate: x509: certificate signed by unknown authority
```

This settles the open question from Appendix A: `argocd-tls-certs-cm`, keyed by **hostname
without port**, is what makes Argo CD trust a private CA for an **OCI** repository, not only for
Git. Restoring it returned the Application to `Synced` / `Healthy`.

Note the ConfigMap change reaches the repo-server only on restart, so a CA rotation needs a
rollout, not just an apply.

## Q1.e — not run

The insecure variant (`insecure: "true"` in the repository Secret) was **not** executed.
Q1.d already demonstrates what the CA is load-bearing for, by removing it and observing the
x509 failure — the risk is documented without ever running the registry without TLS verification.
Recorded as a deliberate omission rather than an oversight.

## Q1.f — least privilege

```text
kubectl auth can-i get secrets -n argocd --as=system:serviceaccount:ok167-demo:default       -> no
kubectl auth can-i get secrets -n argocd --as=system:serviceaccount:ok167-kustomize:default  -> no
kubectl auth can-i get secrets -n argocd --as=system:serviceaccount:argocd:argocd-repo-server -> no
```

Workload ServiceAccounts cannot read the registry credential. The third line is the interesting
one: even the **repo-server's own** ServiceAccount cannot read repository Secrets — Argo CD passes
credentials to it over gRPC rather than letting it read the API. That is a better posture than
the architecture diagram suggests.

Together with V5 (the puller cannot push) and V6 (the publisher is confined to its prefix), the
identity separation required by ADR-028 §4.5 holds at both layers.

## Q1.g — production path (documentation)

1. **Vault + VSO (ADR-025)** renders the repository Secret, or the `repo-creds` template, into
   the `argocd` namespace with the `argocd.argoproj.io/secret-type` label. Git holds the
   `VaultStaticSecret` reference; the value never enters Git. This satisfies ADR-011's Secret
   Contract §2 exactly, and Q1.b makes it one Secret per prefix rather than one per repository.
2. **Rotation** is a Vault-side concern plus a repo-server restart. Q1.c shows recovery is clean
   and the error during the gap is unambiguous.
3. **Identity separation** (ADR-028 §4.5): the CI publisher credential must never be the one
   Argo CD holds. This spike keeps them separate and proves the split is enforced server-side.
4. **htpasswd vs. zot API keys**: htpasswd was used because it is what `registry-default` uses
   for machine identities today. An API key would allow revocation without rewriting the
   htpasswd file, which is worth evaluating separately.

## Verdict

**PASS.** Authentication, authorization and TLS trust all behave as a production design would
need, and the two failure modes most likely in practice — a wrong credential and a missing CA —
produce clear, distinguishable errors and recover cleanly.

## What this proves / What this does not prove

| Proves | Does not prove |
|---|---|
| A `repo-creds` prefix template authenticates OCI repositories that have no exact Secret | That prefix precedence is what one would expect when both exist — untested |
| `argocd-tls-certs-cm` is load-bearing for OCI TLS trust | That it is the *only* way; a cluster-wide trust bundle was not tested |
| A wrong password and a missing CA give distinct, actionable errors | That every failure mode does — T8's registry outage gave only `DeadlineExceeded` |
| Workload ServiceAccounts cannot read the registry credential | That the credential is safe from a cluster-admin or a node compromise |
| Recovery from both failures needed no manual repair beyond fixing the cause | That rotation is zero-downtime — there is a gap until the repo-server restarts |
