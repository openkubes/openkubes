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

## 6. First real login test (`kubectl oidc-login`)

The login test is the only step that actually exercises PKCE, token signing, and JWKS validation (unlike Keycloak's `evaluate-scopes/generate-example-id-token`, which only simulates the mapper).

Intermediate step: `kubectl oidc-login` first failed with a DNS error (`lookup keycloak.ok-shared.internal: no such host`), because the `extraHostEntries` entry only exists on the Talos node, not on the workstation. Fix: added a local `/etc/hosts` entry (`192.168.100.207 keycloak.ok-shared.internal`) — the address is reachable from the workstation.

Next, error #2: `--oidc-extra-scope=groups` is rejected by Keycloak with `invalid_scope`. Without that scope, the authorization-code flow completes all the way to the real Keycloak login screen for realm `openkubes` / client `ok-mgmt` — which already confirms issuer, CA chain, host entry, and client ID are all configured correctly.

Open item: no personal user account exists yet in the realm to actually complete the login screen.

## 7. Open questions for Suchit (posted as an OK-99 comment, 2026-08-05)

- Is a client scope `groups` assigned to client `ok-mgmt` as Default (not just Optional), or is the group-membership mapper attached to a differently named scope?
- Does `make realm` create test users, does the realm federate identities from elsewhere (e.g. LDAP/GitHub OAuth), or does a personal account need to be created manually via the admin console?

## 8. Current status

The machine-config patch is fully applied and verified at every layer (node level, API-server level, existing-auth level). The remaining gap is purely on the Keycloak side (scope assignment, user provisioning) and is no longer part of the Talos/Kubernetes rollout.

## 9. Next steps (pending Suchit's reply)

- Complete the personal login and check the ID token for the `groups` claim
- Wire `RoleBinding Role/openrmf-claim-editor` → subject `oidc:openrmf-claim-editors` (mind the prefix!)
- Positive test: a real login can create an `OpenRMFClaim`
- Negative test: the same login is denied when reading Secrets
- Post a final success comment with the login test result to OK-99
