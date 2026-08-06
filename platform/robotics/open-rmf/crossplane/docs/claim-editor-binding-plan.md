# OpenRMF claim-editor binding plan — resolved

**Ticket:** OK-99
**Status:** the deferred subject decision is made, and the binding manifest now ships as
[`rbac/claim-editor-binding.yaml`](../rbac/claim-editor-binding.yaml). Whether it has been
applied to `ok-mgmt`, and the result of the authorization proof, live in OK-99 — not here.

This file was a plan whose whole purpose was to name what blocked binding
[`openrmf-claim-editor`](../rbac/claim-editor-role.yaml) to a real identity. Those blocks
are gone, so it is now a record of the outcome rather than a set of proposals. The
implementation detail of the `ok-mgmt` side is not restated here — it lives in
[`docs/ok-mgmt-oidc-rollout.md`](../../../../../docs/ok-mgmt-oidc-rollout.md).

## The decision

The subject is the **group** `oidc:openrmf-claim-editors`, bound to the existing namespaced
Role in `openkubes-system`.

The `oidc:` prefix is load-bearing. `ok-mgmt`'s `AuthenticationConfiguration` sets
`claimMappings.groups.prefix: "oidc:"`, so the Keycloak group `openrmf-claim-editors`
arrives at the API server under the prefixed name. A bare group name binds nobody and
Kubernetes reports no error, which is why `make validate` now rejects one.

Kubernetes never sees an individual user grant. Membership is managed in Keycloak
(realm `openkubes`, client `ok-mgmt`), so adding or removing a claim editor never touches
cluster RBAC.

## Resolved dependency chain

Every link below was a blocker in the original plan. Live cluster state must still be
rechecked before acting — this table records what was true when each link closed, not a
standing guarantee.

| Order | Link | Resolution |
|---:|---|---|
| 1 | Claim API and least-privilege Role exist | Unchanged. `openkubes-system`, the `openrmfclaims` CRD, and the Role are on `ok-mgmt`; the Role grants no Secret access |
| 2 | Choose an authenticatable subject | **Group `oidc:openrmf-claim-editors`.** The interim ServiceAccount was rejected — see below |
| 3 | Stable OIDC issuer | `https://keycloak.ok-shared.internal/realms/openkubes`, serving TLS, no port-forward |
| 4 | Issuer name resolvable and reachable | `machine.network.extraHostEntries` on the Talos nodes → `192.168.100.207` → Traefik TLS passthrough. **Not** a CoreDNS entry: the API server runs `hostNetwork`, so its `dnsPolicy` is downgraded to `Default` and CoreDNS is never consulted. Human/browser DNS remains OK-57 |
| 5 | Certificate the API server trusts | ADR-025 CA via `ClusterIssuer/ok-shared-internal-ca`, delivered inline as `certificateAuthority` in the authentication config rather than a mounted `--oidc-ca-file` |
| 6 | Production realm, client, groups | Realm `openkubes`, public client `ok-mgmt` (PKCE S256), groups `openrmf-claim-editors` and `platform-admins`, reproducible via `make realm` |
| 7 | `ok-mgmt` accepts those tokens | Structured `AuthenticationConfiguration` (`--authentication-config`), **not** the deprecated `--oidc-*` flags |
| 8 | Bind the subject to the Role | This change |
| 9 | Exercise both authorization boundaries | See *Proof standard* below |

Central OIDC remains opt-in under
[ADR-Platform-020 §4](../../../../../architecture/decisions/ADR-Platform-020-shared-platform-services.md#4-relationship-to-adr-018--strictly-additive).
Enabling it on `ok-mgmt` does not make it a platform default; that would need an ADR
amendment and is outside OK-99.

## Why the interim ServiceAccount was not used

It was justified only if a Claim had to land before an `ok-mgmt` maintenance window could
be scheduled. The window happened, so the interim's costs bought nothing: a bearer token
puts no human identity in the audit log, and its issuance, rotation and revocation
procedure had no owner. The alternative interim — an x509 `User`/`Group` — needed the
privileged client-CA signing path and a key-delivery procedure that does not exist here.

## Proof standard

The positive half proves the authentication, mapper, API-server and RoleBinding chain
together. The Secret denial proves the Role still provides the isolation it was created
for. **Either half failing rejects the binding.**

This plan originally required both halves to run under one real human login, explicitly
disallowing impersonation and `kubectl auth can-i`. That standard was **relaxed for the
OK-99 rollout**, and the reason is recorded here rather than left implicit:

- **Authentication** is evidenced by a real `kubectl oidc-login` completing the full
  authorization-code + PKCE flow, with the decoded ID token carrying the expected
  `groups`, `aud` and `iss`. That evidence is on **OK-99 (comment 13185)**. Note that
  [`docs/ok-mgmt-oidc-rollout.md`](../../../../../docs/ok-mgmt-oidc-rollout.md) on `main`
  still records the earlier state, where the flow reached the login screen but no token
  was issued; the update is in flight as openkubes PR #58. Read the ticket, not that file,
  until #58 lands.
- **Authorization** is evidenced by `make authz-check`, which impersonates the subject.
  An impersonated request is resolved by the same authorizer, against the same RBAC rules,
  as a bearer-token request — so it is authoritative for authorization, and it needs
  nobody's credentials, which matters because the only realm account belongs to another
  person. (A normal request does not itself create a `SubjectAccessReview`; both paths
  simply reach the same evaluator.)

Two limits to state wherever this evidence is cited — do not describe the pair as a single
end-to-end human proof:

- No human, in one session, used their own token for both halves. The realm has no
  persistent claim-editor account created reproducibly, so that waits on user provisioning
  being folded into `keycloak-realm-provision.sh`.
- Impersonation supplies the groups directly. It therefore never exercises the token, the
  Keycloak group mapper, or the client scope. If a real login's token carried no `groups`
  claim, `authz-check` would still pass while that user got `Forbidden` — and Kubernetes
  would log nothing useful. Only the decoded-token evidence above closes that gap.

What `make authz-check` asserts for the impersonated subject: `create openrmfclaims` in
`openkubes-system` is allowed (retried briefly, because the authorizer's cache lags a
fresh binding); a server-side dry-run create of the Claim succeeds; `get` and `list` on
Secrets are denied in `openkubes-system`, `crossplane-system`, `kube-system` and
`default`; and no blanket `'*' '*'` grant exists.

Two things it deliberately does not claim. `auth can-i --all-namespaces` issues one review
with an empty namespace, so it would not notice a per-namespace RoleBinding — hence the
enumerated list rather than a blanket "no Secret access anywhere". And `'*' '*'` detects
only a literal wildcard rule, so it rules out cluster-admin-shaped grants, not every
individual cluster-scoped permission.

Every negative is asserted twice: once for the claim-editor group alone, and once with
`PEER_GROUPS` (default `oidc:platform-admins`) added, because the observed token carries
both and a negative is only as strong as the subject it runs against.

## Still human-owned

1. Applying the RoleBinding and the Claim on `ok-mgmt` — `make bind` and `make deploy`
   both require `APPROVE_MGMT=yes`, an attended terminal, a verified `ok-mgmt`
   kubeconfig, and a typed confirmation after a server-side dry run.
2. Keycloak group membership, and deciding whether persistent user provisioning belongs
   in `keycloak-realm-provision.sh`.
3. Disposition of anything a Claim creates downstream. The composed Release is
   `deletionPolicy: Orphan`, so deleting a Claim leaves it running — see the README's
   stateful lifecycle policy.

## Reverification commands

Read-only, immediately before acting:

```bash
# Switch and command must remain in the same shell invocation.
okm && kubectl get namespace openkubes-system
okm && kubectl get crd openrmfclaims.platform.openkubes.ai
okm && kubectl get role openrmf-claim-editor -n openkubes-system -o yaml
# NotFound before `make bind`, which is the expected pre-state, not a fault:
okm && kubectl get rolebinding openrmf-claim-editor -n openkubes-system -o yaml

# Parse each kube-apiserver container's command/args with a JSON parser; do not grep
# merged stderr. `--authentication-config` is now expected to be PRESENT, and any
# `--oidc-*` flag alongside it is the anomaly worth stopping for.
okm && kubectl get pods -n kube-system -l component=kube-apiserver -o json

oks && kubectl get statefulset keycloak -n keycloak -o json
oks && kubectl get clusterissuers.cert-manager.io -o json
```
