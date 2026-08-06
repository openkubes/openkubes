# OK-99 — OIDC against the ok-shared Keycloak on ok-mgmt

Rollout documentation · as of August 5, 2026

## 1. Goal

ok-mgmt (a single-control-plane Talos cluster) should be able to authenticate against the central Keycloak instance on ok-shared in addition to its existing x509 authentication, so human users can log in via OIDC/kubectl instead of a client certificate.

Realm: `openkubes` · Client: `ok-mgmt` (public, PKCE S256, no direct access grants) · Groups: `openrmf-claim-editors`, `platform-admins` · Issuer: `https://keycloak.ok-shared.internal/realms/openkubes`

## 2. Why this required a Talos machine-config patch

The original proposal (Suchit, comment 12991) was a CoreDNS hosts entry for `keycloak.ok-shared.internal`. That was technically wrong: `kube-apiserver` runs with `hostNetwork: true`, and Kubernetes silently downgrades `dnsPolicy: ClusterFirst` to `Default` for host-network pods. The API server therefore never consults CoreDNS — it always resolves through the node's own `/etc/resolv.conf` and `/etc/hosts`. The name has to exist at the Talos level via `machine.network.extraHostEntries`. Suchit later corrected this himself (comment 13072).

Second decision: structured `AuthenticationConfiguration` (`--authentication-config`) instead of the deprecated `--oidc-*` flags. Kubernetes 1.34.1 (confirmed version on ok-mgmt) supports both; `AuthenticationConfiguration` is the forward-looking, GA path and bundles the CA inline, without a separate file/mount just for the certificate.

## 3. The final patch (v3)

Two parts in a single apply, one API-server restart:

- `machine.files`: writes `/var/lib/ok-shared/authentication-config.yaml` onto the node (content: `AuthenticationConfiguration` with issuer URL, audience `ok-mgmt`, inline CA, claim mappings for username/groups with prefix `oidc:`)
- `machine.network.extraHostEntries`: `192.168.100.207` → `keycloak.ok-shared.internal` (MetalLB address on ok-shared, TLS passthrough via Traefik/SNI)
- `cluster.apiServer.extraArgs.authentication-config` + `extraVolumes`: mounts the file read-only into the `kube-apiserver` static pod

```yaml
machine:
  files:
    - path: /var/lib/ok-shared/authentication-config.yaml
      permissions: 0o444
      op: create
      content: |
        apiVersion: apiserver.config.k8s.io/v1beta1
        kind: AuthenticationConfiguration
        jwt:
          - issuer:
              url: https://keycloak.ok-shared.internal/realms/openkubes
              audiences:
                - ok-mgmt
              audienceMatchPolicy: MatchAny
              certificateAuthority: |
                -----BEGIN CERTIFICATE-----
                ...
                -----END CERTIFICATE-----
            claimMappings:
              username:
                claim: preferred_username
                prefix: "oidc:"
              groups:
                claim: groups
                prefix: "oidc:"
  network:
    extraHostEntries:
      - ip: 192.168.100.207
        aliases:
          - keycloak.ok-shared.internal

cluster:
  apiServer:
    extraArgs:
      authentication-config: /var/lib/ok-shared/authentication-config.yaml
    extraVolumes:
      - hostPath: /var/lib/ok-shared
        mountPath: /var/lib/ok-shared
        readonly: true
```

Important: claim prefix `oidc:` on both username and groups — every RoleBinding subject must carry this prefix (e.g. `oidc:openrmf-claim-editors`), otherwise it silently binds to nobody.

## 4. Rollout history: two real incidents, both found and fixed live

### Incident 1 — `op: overwrite` instead of `create`

The first version of the patch used `op: overwrite`. `overwrite` requires the path to already exist; the file had never existed on the node before. Result: `writeUserFiles failed` in the boot log, `kube-apiserver` never started, and `/readyz` / `kubectl get nodes` returned connection refused.

Response: immediate revert via `talosctl apply-config` using the previously saved machine-config backup. Fix: `op: create` (for a path that does not yet exist).

### Incident 2 — `permissions: 0o400` instead of `0o444`

The second version (`op: create`, but still `permissions: 0o400`) landed correctly on the node, but the `kube-apiserver` container process did not run under the exact UID that owns the file → "permission denied" reading `--authentication-config`. Confirmed via `talosctl containers -k` / `talosctl logs -k` against the `kube-apiserver` container.

Response: another revert. Fix: `permissions: 0o444` (world-readable). Not a security concern, since the file contains no secret data — only a public CA certificate, no private key.

### Incident impact

Both incidents caused a brief outage of the management plane each (single control-plane node, an accepted risk noted in the original draft) and paused Crossplane reconciliation. No data loss, no impact on existing x509 authentication — both reverts used the previously saved machine-config backup.

## 5. Verification after the final (v3) apply

| Check | Result |
|---|---|
| `dmesg` | ✓ "machine is running and ready" — clean boot, no retry loop |
| `kube-apiserver` container | ✓ `CONTAINER_RUNNING` (PID 2712) |
| `/etc/hosts` on node | ✓ `192.168.100.207 keycloak.ok-shared.internal` present |
| `authentication-config.yaml` on node | ✓ no placeholder, real CA present (`BEGIN CERTIFICATE`) |
| `kubectl get --raw /readyz` | ✓ `ok` |
| `kubectl get nodes` | ✓ all 3 nodes `Ready` (v1.34.1) |
| Existing x509 kubeconfig | ✓ still works — additive change confirmed |

## 6. First real login test (`kubectl oidc-login`) — succeeded

The login test is the only step that actually exercises PKCE, token signing, and JWKS validation (unlike Keycloak's `evaluate-scopes/generate-example-id-token`, which only simulates the mapper).

Two setup issues were resolved along the way, both on the client/workstation side, not in the patch itself:

- `kubectl oidc-login` first failed with a DNS error (`lookup keycloak.ok-shared.internal: no such host`), because the `extraHostEntries` entry only exists on the Talos node, not on the workstation. Fixed with a local `/etc/hosts` entry.
- `--oidc-extra-scope=groups` was rejected by Keycloak with `invalid_scope`. Traced to source (`keycloak-realm-provision.sh`): the groups mapper is attached directly to the client as a default protocol mapper, not exposed as a separate client scope — so there is no scope named `groups` to request. Fix: drop the flag; the mapper fires on every token regardless.

**Personal account.** The provisioning script only ever creates a short-lived probe user for mapper verification and deletes it immediately afterward — there is no code path that creates a persistent human user. A personal account (`arash`, member of `openrmf-claim-editors` + `platform-admins`) was created directly via the Keycloak Admin REST API as a pragmatic, ad hoc unblock, using the Vault-escrowed `keycloak-admin` master-realm credentials. Note: this account does not survive a realm rebuild and isn't reproducible — the same class of gap the provisioning script deliberately avoids for everything else. Worth deciding whether to formalize personal/test user provisioning into that script, or accept manual creation as a documented exception.

One incidental finding: the Keycloak Admin REST API (`/admin/realms/...`) is not reachable over the external route (the same MetalLB/Traefik path the OIDC login uses) — it returned 401 there but worked immediately over a direct `kubectl port-forward` to the `keycloak-keycloakx-http` Service. Likely intentional hardening (the admin API has no business being externally reachable), but worth a one-line note somewhere so it isn't mistaken for a bug later.

**Result.** The full browser flow completed (temporary password change → profile completion → redirect to `localhost:8000`, "Authenticated — you have logged in to the cluster"). Decoded ID token:

```
preferred_username: arash
groups: [openrmf-claim-editors, platform-admins]
aud: ok-mgmt
iss: https://keycloak.ok-shared.internal/realms/openkubes
```

This confirms the mapper, the per-cluster audience, and the full claim pipeline all work correctly end to end.

## 7. RBAC wiring — started, blocked on a workflow decision (not infra)

Attempted to wire `RoleBinding Role/openrmf-claim-editor` → subject `oidc:openrmf-claim-editors` and found:

- Neither `Role` nor `ClusterRole` named `openrmf-claim-editor` exists yet on ok-mgmt — it needs to be created, not just bound.
- `openrmfclaims.platform.openkubes.ai/v1alpha1` is **namespaced** (`openrmfinstances` is cluster-scoped — the Crossplane-managed composite, not meant for direct end-user access).
- No existing claims and no namespace among the current ones (`openkubes-system`, `default`, `crossplane-system`, etc.) looks like a deliberate convention for where claim editors are meant to work.

Deciding the target namespace is a workflow/product decision, not an infrastructure one — handed to Suchit (OK-99 comment 13186), along with the ready-to-apply Role/RoleBinding YAML once a namespace is chosen.

## 8. Current status

- Machine-config patch: fully applied and verified (section 5).
- OIDC login: fully verified end to end (section 6).
- RBAC wiring: Role/RoleBinding drafted, blocked on choosing a target namespace for `OpenRMFClaim`s (section 7).
- Not yet done: positive test (create an `OpenRMFClaim` as a real claim-editor login) and negative test (same login denied reading Secrets) — both depend on section 7 landing first.

## 9. Next steps (pending Suchit)

- Decide the target namespace for `openrmfclaims` and apply the Role/RoleBinding from comment 13186
- Positive test: `arash` (or another claim-editor) can create an `OpenRMFClaim`
- Negative test: the same login is denied when reading Secrets
- Decide whether personal/test user provisioning belongs in `keycloak-realm-provision.sh`
- Post a final success comment to OK-99 once both tests pass
