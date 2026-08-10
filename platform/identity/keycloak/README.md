# Central Keycloak

> **Operator procedure:** read the [central Keycloak runbook](RUNBOOK.md) before installing, rebuilding, rotating credentials, restoring, or tearing down this service.

This directory provides the central OIDC identity capability on ok-shared. Keycloak serves TLS from a cert-manager certificate and is exposed through Traefik TLS passthrough; verification pins the stable SNI name to a local HTTPS port-forward and does not depend on DNS.

The capability Makefile is the operational entry point:

```bash
make help
make install-vso CLUSTER=<name> NAMESPACE=<namespace> KUBECONFIG=<path>
make identities CLUSTER=<name> NAMESPACE=<namespace> KUBECONFIG=<path>
make reachability CLUSTER=<name> NAMESPACE=<namespace> KUBECONFIG=<path>
make vault-config CLUSTER=<name> NAMESPACE=<namespace> KUBECONFIG=<path> \
  MGMT_KUBECONFIG=<path> APPROVE_MGMT=yes
make install CLUSTER=<name> NAMESPACE=<namespace> KUBECONFIG=<path> MGMT_KUBECONFIG=<path> \
  APPROVE_CUTOVER=yes APPROVE_NETWORK_POLICY=yes
```

RMF Web uses a dedicated application realm on the same central Keycloak instance. Provision it
with the exact browser origin; the target permits only `<origin>/*` redirects and reads RMF Web's
built-in administrator password from `crossplane-system/rmf-credentials` on ok-mgmt without
placing either password in argv, the environment, a log, or a file:

```bash
make rmf-realm CLUSTER=ok-shared NAMESPACE=keycloak KUBECONFIG=<ok-shared-kubeconfig> \
  MGMT_KUBECONFIG=<ok-mgmt-kubeconfig> RMF_WEB_ORIGIN=https://robotics.openkubes.local \
  APPROVE_RMF_REALM=yes
```

The target reconciles realm `rmf-web`, browser client `dashboard`, service client `smart_cart`,
the `dashboard` audience scope, and application user `admin`. It verifies the Admin API shape,
obtains a real dashboard token through discovery and checks `aud=dashboard`, then writes only the
realm signing public key PEM to stdout; progress and the idempotency result go to stderr. Redirect
origins are deliberately per invocation rather than wildcarded across hosts. The central server
does not provide RMF's custom `jsonlog_event_listener`, so this target leaves realm event settings
untouched instead of pretending the built-in JBoss logger is format-compatible. No deployed chart
workload consumes `smart_cart`'s generated client secret, so the target neither reads nor escrows it.

On an empty database the bootstrap environment wiring mints the first `admin` from the
Vault-materialised `keycloak-admin` Secret. `install` requires `APPROVE_CUTOVER=yes` and
`APPROVE_NETWORK_POLICY=yes` in an attended terminal, then promotes that temporary account to the
permanent `admin`, runs `verify`, and applies the required brute-force and NetworkPolicy hardening.
The explicit approvals prevent an aggregate install from silently rewriting admin identity or
changing live traffic isolation; requiring them at entry also prevents a routine install from
stopping in a no-login or unhardened state. Credential rotation and break-glass recovery remain
separate approved operations:

```bash
make admin-cutover CLUSTER=<name> NAMESPACE=<namespace> KUBECONFIG=<path> APPROVE_CUTOVER=yes
make rotation-test CLUSTER=<name> NAMESPACE=<namespace> KUBECONFIG=<path> APPROVE_CUTOVER=yes
make recover-admin CLUSTER=<name> NAMESPACE=<namespace> KUBECONFIG=<path> APPROVE_CUTOVER=yes
```

`admin-cutover` creates the permanent `admin`, escrows it to the existing
`secret/<cluster>/keycloak/admin` path **before** deleting the temporary account, and asserts no
account is left carrying the temporary flag. `recover-admin` is break-glass only, for when no known
admin credential works. These targets retain their work directories (mode 700, plaintext
credentials, path printed) because a cleanup trap once destroyed the only copy of a generated admin
password — delete them yourself once you are satisfied.

The hardening operations are exposed as the same kind of independently verifiable targets:

```bash
make backup CLUSTER=<name> NAMESPACE=<namespace> KUBECONFIG=<path> [BACKUP_DIR=<local-dir>]
make restore-drill CLUSTER=<name> NAMESPACE=<namespace> KUBECONFIG=<path> \
  RESTORE_FILE=<dump> APPROVE_RESTORE_DRILL=yes
make brute-force CLUSTER=<name> NAMESPACE=<namespace> KUBECONFIG=<path>
# Apply last: this proves allowed traffic, blocked external access, CNPG readiness and API reachability.
make network-policy CLUSTER=<name> NAMESPACE=<namespace> KUBECONFIG=<path> APPROVE_NETWORK_POLICY=yes
```

`backup` streams a compressed PostgreSQL custom-format dump to a caller-supplied local directory
or a retained mode-700 work directory. Local disk is the only available target in this profile; it
is a restorable copy, not durable off-host backup storage. `restore-drill` creates a uniquely named
scratch database on the same PostgreSQL server, restores the dump without connecting Keycloak to
it, asserts realm and client row counts, and drops the scratch database on every exit. The dump and
local work directories are retained.

The NetworkPolicy implementation uses portable Kubernetes `NetworkPolicy`: pod/namespace
selectors and port restrictions cover this boundary, so no Cilium-specific capability is needed.
VSO still reconciles through the Kubernetes API, CNPG controller traffic to the instance manager
is allowed, and CNPG can report to the API server. The target runs conformance to prove the allowed
Keycloak-to-database path, then starts a disposable pod in `default` and requires ports 9000 and
5432 to be blocked. It also requires CNPG `Ready=True` and rejects recent instance logs containing
`apiServerReachable:false`. It no longer deletes the database Secret or waits for an unchanged
password's resourceVersion to advance: CNPG need not re-apply unchanged credentials, so that wait
was slow and could fail a correct policy. On any proof failure, each pre-existing policy is restored
in place and only policies introduced by that run are removed; a rerun cannot delete a policy that
existed when it started.

`install` never applies the privileged management-plane configuration. Review and run
the VSO and identity bootstrap targets first, then run `make vault-config ... APPROVE_MGMT=yes`
separately. The aggregate `install` checks that `VaultConfig` is currently `Synced=True` and
`Ready=True` and checks cutover and NetworkPolicy approvals before its first mutation. It then runs
the bootstrap sequence, installs Keycloak, performs the idempotent admin cutover, verifies with the
newly escrowed permanent credential, applies hardening, and runs the post-check. `verify` belongs
after cutover: if it ran only before, a cutover or escrow failure could leave the final identity
untested.

Teardown destroys the CNPG PVC and therefore all realm state. Back it up first, then use
`make teardown ... CONFIRM=yes`. Normal teardown deliberately retains the ok-mgmt reviewer JWT,
the `VaultConfig` XR, Vault auth/policies/roles, and KV entries.

Parameterized raw resources remain under `manifests/` because they are neither Crossplane
resources, conformance assets, tooling, nor runbooks. Identities, VSO wiring, the database, and
Keycloak TLS reachability, and network isolation are separate templates so installation and teardown preserve their dependency
order and `make render`/`make diff` always use the same source.

The [phase-1 run log](PHASE1-RUNLOG.md) is the authoritative record behind the targets. The older
[deployment document](../../../docs/ok81-keycloak-deployment.md) remains background only.
