# Central Keycloak operator runbook

This is the procedure for the central Keycloak service on `ok-shared`, normally in
namespace `keycloak`. It uses the capability Makefile as the operational interface;
do not replace its targets with hand-written `kubectl` or `helm` commands.

The [phase-1 run log](PHASE1-RUNLOG.md) is historical evidence. The
[deployment document](../../../docs/ok81-keycloak-deployment.md) records background
and decisions. Neither is the execution procedure.

## Safety and prerequisites

* Work from the `ok-cluster` checkout for the lifecycle entry point and from the
  `openkubes` checkout for this capability. The checkouts are siblings, for example
  `~/temp/kubernauts/ok/ok-cluster` and `~/temp/kubernauts/ok/openkubes`.
* Use a real kubeconfig path as a Make variable; do not export `KUBECONFIG` manually.
  Commands below use placeholders and never contain credentials.
* The target cluster is `ok-shared`; `MGMT_KUBECONFIG` is only for the separately
  approved management-plane step or an explicitly documented read-only check. The
  installer currently validates the management context only on the mutating
  `vault-config` target, not on its read-only prerequisite query, so independently
  confirm that the supplied management kubeconfig identifies `ok-mgmt`.
* Required tools include `kubectl`, `helm`, `make`, `python3`, `jq`, `openssl`,
  `curl`, `base64`, `sha256sum`, `realpath`, `rg`, `git`, `tar` and `flock`.
* Keep these sibling inputs available and pinned: the Keycloak chart checkout at
  tag `keycloakx-7.2.2` (`keycloak/charts/keycloakx`) and the CNPG checkout/manifest
  at `v1.30.0` (`cnpg/releases/cnpg-1.30.0.yaml`). The capability Makefile also
  needs the `ok-cluster` checkout for its VSO callback. Do not fetch a chart at
  install time.
* `ok-cluster/ok-keycloak.ref` must name the OpenKubes revision to consume. The
  default mode is pinned; `OK_KEYCLOAK_MODE=worktree` is an explicitly
  non-reproducible exception and should not be used for a normal operation.
* Review the target-specific approval requirements before running any mutating
  operation. `vault-config`, `admin-cutover`, `rotation-test`, `recover-admin`,
  `restore-drill`, and `network-policy` require attended execution. `teardown` is
  destructive but its Make target has only the explicit `CONFIRM=yes` guard; it can
  run unattended, so process approval and the backup check remain operator duties.

Start with the available targets:

```bash
cd ~/temp/kubernauts/ok/ok-cluster
make help
cd ~/temp/kubernauts/ok/openkubes/platform/identity/keycloak
make help
```

## Install, rebuild, and repeat operations

### First installation

A first installation has one extra bootstrap seam: `VaultConfig/ok-shared` needs the
reviewer identity from `ok-shared`, while the pinned `ok-cluster` installer correctly
refuses to start until that `VaultConfig` is already `Synced=True` and `Ready=True`.
Create only those prerequisites from the reviewed capability checkout first:

```bash
cd ~/temp/kubernauts/ok/openkubes/platform/identity/keycloak
make baseline CLUSTER=ok-shared NAMESPACE=keycloak \
  KUBECONFIG=<ok-shared-kubeconfig>

cd ~/temp/kubernauts/ok/ok-cluster
make install-vso CLUSTER=ok-shared

cd ~/temp/kubernauts/ok/openkubes/platform/identity/keycloak
make identities CLUSTER=ok-shared NAMESPACE=keycloak \
  KUBECONFIG=<ok-shared-kubeconfig>
```

The first VSO installation uses the `ok-cluster` lifecycle target because a genuinely
fresh cluster has none of the VSO CRDs that the capability target inventories before
activation. Once the operator and CRDs exist, the pinned Keycloak installer can rerun
that target idempotently and apply the capability resources safely.

`identities` creates and verifies the reviewer ServiceAccount and its populated token
Secret. Only after that succeeds may an operator review and run the separately gated
management-plane step:

```bash
make vault-config CLUSTER=ok-shared NAMESPACE=keycloak \
  KUBECONFIG=<ok-shared-kubeconfig> MGMT_KUBECONFIG=<ok-mgmt-kubeconfig> \
  APPROVE_MGMT=yes
```

Run `vault-config` from an attended terminal. It reviews both the reviewer-token
Secret and the `VaultConfig` apply; neither the capability's `install` target nor the
consumer installer applies this privileged prerequisite. Wait for the XR to report
both `Synced=True` and `Ready=True`.

Now use the consumer entry point. It materialises the revision in
`ok-cluster/ok-keycloak.ref`, passes the pinned sibling inputs to the capability, and
stops before the remaining attended gates:

```bash
cd ~/temp/kubernauts/ok/ok-cluster
make install-keycloak CLUSTER=ok-shared \
  OK_KEYCLOAK_PATH=~/temp/kubernauts/ok/openkubes
```

With the standard sibling layout, the installer resolves the pinned chart and CNPG
manifest described above. If those checkouts live elsewhere, use the installer's
explicit vendor-path overrides while retaining the same pinned revisions; do not
substitute a registry chart. The `ok-cluster` lifecycle targets currently address
`~/.kube/ok-shared.yaml` and `~/.kube/ok-mgmt.yaml` directly; ensure those files
identify the intended clusters. Do not try to mix an alternate capability
`KUBECONFIG` with these targets, because VSO could otherwise be installed on a
different cluster. Never place credential values in command arguments or logs.

The installer runs, in order, the baseline, VSO, identities, one-time seed, VSO
wiring, CNPG database, TLS-resource setup, and Keycloak chart targets. It intentionally
stops before admin cutover and network-policy hardening. The `reachability` target
creates the certificate and route; functional endpoint and OIDC reachability are not
proved until the later `verify` target passes. Complete those gates in an
attended terminal, in this order:

```bash
cd ~/temp/kubernauts/ok/openkubes/platform/identity/keycloak
make admin-cutover CLUSTER=ok-shared NAMESPACE=keycloak \
  KUBECONFIG=<ok-shared-kubeconfig> APPROVE_CUTOVER=yes
make verify CLUSTER=ok-shared NAMESPACE=keycloak KUBECONFIG=<ok-shared-kubeconfig>
make harden CLUSTER=ok-shared NAMESPACE=keycloak \
  KUBECONFIG=<ok-shared-kubeconfig> APPROVE_NETWORK_POLICY=yes
make post-check CLUSTER=ok-shared NAMESPACE=keycloak \
  KUBECONFIG=<ok-shared-kubeconfig>
```

`harden` enables brute-force protection and then applies NetworkPolicy. The
NetworkPolicy approval is separate and last because it changes live traffic; the
target proves Keycloak-to-database traffic, blocked external ports, CNPG readiness,
and API reachability, and restores the pre-run policy set if proof fails.

For a fully attended capability-owned lifecycle (rather than the consumer wrapper),
`make install` performs the same ordered bootstrap, cutover, verification, hardening,
and post-check, but still requires the existing `VaultConfig` and explicit
`APPROVE_CUTOVER=yes` and `APPROVE_NETWORK_POLICY=yes` gates:

```bash
make install CLUSTER=ok-shared NAMESPACE=keycloak \
  KUBECONFIG=<ok-shared-kubeconfig> MGMT_KUBECONFIG=<ok-mgmt-kubeconfig> \
  APPROVE_CUTOVER=yes APPROVE_NETWORK_POLICY=yes
```

### Repeat checks and service rebuild

Do **not** rerun `make install-keycloak` as a health check or after the service has
already been seeded. The installer always includes the one-time `seed` target, whose
CAS-zero writes correctly fail when the retained Vault paths already exist. Use
`diff`, `verify`, and `post-check` for routine checks, and `rotation-test` for
credential rotation.

After this runbook's `teardown` on the same `ok-shared` cluster, Vault credentials and
`VaultConfig` are deliberately retained. Rebuild from a clean checkout at the
revision named by `ok-cluster/ok-keycloak.ref`, verify that `VaultConfig/ok-shared`
still reports `Synced=True` and `Ready=True`, and run the component targets without
the one-time seed:

```bash
cd ~/temp/kubernauts/ok/openkubes/platform/identity/keycloak
make baseline CLUSTER=ok-shared NAMESPACE=keycloak \
  KUBECONFIG=<ok-shared-kubeconfig>
make install-vso CLUSTER=ok-shared NAMESPACE=keycloak \
  KUBECONFIG=<ok-shared-kubeconfig>
make identities CLUSTER=ok-shared NAMESPACE=keycloak \
  KUBECONFIG=<ok-shared-kubeconfig>
make vso-wiring CLUSTER=ok-shared NAMESPACE=keycloak \
  KUBECONFIG=<ok-shared-kubeconfig>
make database CLUSTER=ok-shared NAMESPACE=keycloak \
  KUBECONFIG=<ok-shared-kubeconfig>
make reachability CLUSTER=ok-shared NAMESPACE=keycloak \
  KUBECONFIG=<ok-shared-kubeconfig>
make keycloak CLUSTER=ok-shared NAMESPACE=keycloak \
  KUBECONFIG=<ok-shared-kubeconfig>
```

Then run the attended `admin-cutover`, `verify`, `harden`, and `post-check` sequence
from the first-install section. An empty database recreates Keycloak's temporary
bootstrap admin from the retained Vault-materialised credential; the cutover is still
required. This sequence is for a Keycloak service rebuild on the same cluster. A
recreated `ok-shared` cluster has a new reviewer identity and requires the first-install
identity plus attended `vault-config` refresh before VSO wiring; do not reuse a stale
reviewer JWT.

## Verification and routine checks

Read-only checks and their purpose:

```bash
cd ~/temp/kubernauts/ok/openkubes/platform/identity/keycloak
make render CLUSTER=ok-shared NAMESPACE=keycloak
make diff CLUSTER=ok-shared NAMESPACE=keycloak KUBECONFIG=<ok-shared-kubeconfig>
make verify CLUSTER=ok-shared NAMESPACE=keycloak KUBECONFIG=<ok-shared-kubeconfig>
make post-check CLUSTER=ok-shared NAMESPACE=keycloak KUBECONFIG=<ok-shared-kubeconfig>
```

`render` shows the exact parameterised resources; `diff` exits non-zero on drift.
`verify` owns a TLS port-forward, validates the discovery issuer and OIDC
conformance, and checks the advertised SNI/origin without depending on DNS.
`post-check` repeats the Vault baseline, current VSO sync, CNPG `Ready=True`, and
StatefulSet readiness. `make help` is the authoritative target list.

For drift investigation, save the output of `make render` for review and run `make
diff`; do not reconcile by hand. If the chart or CNPG pin check fails, restore the
expected sibling checkout/tag or pass the reviewed pinned path. Do not bypass
`require-chart`, `require-cnpg`, or the values contract.

## Realms and clients

The platform realm is provisioned idempotently after Keycloak is verified. It creates
the `openkubes` realm, configured groups, and the per-cluster `ok-mgmt` OIDC client:

```bash
make realm CLUSTER=ok-shared NAMESPACE=keycloak \
  KUBECONFIG=<ok-shared-kubeconfig>
```

The target verifies the Admin API, discovery, a real token and its audience, and
writes only the realm signing public key to stdout. Add a platform client by passing
the reviewed `PLATFORM_CLIENTS` value; do not invent wildcard redirect origins.

RMF Web is a separate attended application-realm operation. Supply the exact browser
origin, and let the target read its existing administrator credential from the
management-plane Secret without exposing it:

```bash
make rmf-realm CLUSTER=ok-shared NAMESPACE=keycloak \
  KUBECONFIG=<ok-shared-kubeconfig> MGMT_KUBECONFIG=<ok-mgmt-kubeconfig> \
  RMF_WEB_ORIGIN=https://<rmf-web-host> APPROVE_RMF_REALM=yes
```

This creates/reconciles `rmf-web`, its clients, audience scope, and application admin.
The approval is for application identity objects; the command must be attended as
required by the target. The central server does not provide RMF's custom event
listener, so event settings are intentionally not changed.

## Backups and restore drills

Back up before any teardown, database-affecting change, or planned rebuild:

```bash
make backup CLUSTER=ok-shared NAMESPACE=keycloak \
  KUBECONFIG=<ok-shared-kubeconfig> BACKUP_DIR=<mode-700-local-backup-dir>
```

The target streams a compressed PostgreSQL custom-format dump and retains the dump
and work directory. Local disk is not off-host durable backup: a host, node, or
workspace loss can lose both the database and its only backup. There is no scheduler
or off-host target in this profile; arrange that separately before calling the
service protected.

A restore drill never points Keycloak at the restored database. It creates a uniquely
named scratch database on the live PostgreSQL server, restores the dump, checks realm
and client row counts, and drops the scratch database on exit:

```bash
make restore-drill CLUSTER=ok-shared NAMESPACE=keycloak \
  KUBECONFIG=<ok-shared-kubeconfig> RESTORE_FILE=<path-to-dump> \
  APPROVE_RESTORE_DRILL=yes
```

This is attended and creates/drops live database state. It is a drill, not a disaster
recovery procedure or proof of off-host durability.

## Credentials, rotation, and break-glass

Do not print, copy, or place credentials in command arguments, environment values,
logs, or documentation. The Make targets stream them from Vault/Kubernetes Secrets.
The temporary bootstrap admin is replaced by `admin` only by the attended cutover;
Vault escrow occurs before the temporary account is deleted.

Exercise the full admin and database rotation path, rather than changing Vault alone:

```bash
make rotation-test CLUSTER=ok-shared NAMESPACE=keycloak \
  KUBECONFIG=<ok-shared-kubeconfig> APPROVE_CUTOVER=yes
```

The target proves old credentials fail, Keycloak's admin credential and the CNPG role
are changed through their proper authorities, VSO converges, and Keycloak is restarted
so Secret-backed environment variables are consumed. A Vault value change by itself
does not change an existing Keycloak admin account.

Use break-glass only when no known admin credential works:

```bash
make recover-admin CLUSTER=ok-shared NAMESPACE=keycloak \
  KUBECONFIG=<ok-shared-kubeconfig> APPROVE_CUTOVER=yes
```

It creates a temporary recovery admin, retains a mode-700 work directory, and prints
the directory path. Immediately follow it with the attended `admin-cutover`, then
`verify`. Never delete the retained directory until the new credential is confirmed
escrowed and usable; then securely remove the directory and any retained dump or
credential-bearing work files according to local incident procedures. The runbook does
not contain credentials.

## Rollback, teardown, and limitations

For an ordinary failed upgrade, stop and use the Makefile's verification and rollback
path; do not delete resources by hand. If a chart/value change leaves Helm and the
cluster disagreeing on environment wiring, use the documented rebuild path rather
than fighting a three-way merge.

`teardown` is destructive. Take a fresh `make backup` first, confirm the dump is
readable, and obtain approval before proceeding. `CONFIRM=yes` is only the target's
mechanical deletion guard: it does not verify that a backup exists and it does not
require an attended terminal, so the operator must enforce those prerequisites:

```bash
make teardown CLUSTER=ok-shared NAMESPACE=keycloak \
  KUBECONFIG=<ok-shared-kubeconfig> CNPG_MANIFEST=~/temp/kubernauts/ok/cnpg/releases/cnpg-1.30.0.yaml \
  CONFIRM=yes
```

It uninstalls Keycloak, deletes the CNPG Cluster and its `Delete`-reclaim PVC (all
realm state), removes VSO wiring and the app namespace, and uninstalls VSO. Before
running it, confirm no other workload on `ok-shared` consumes that cluster-wide VSO
installation; otherwise use only the reviewed component teardown targets and retain
VSO. The top-level teardown retains
the reviewer identity, reviewer JWT, `VaultConfig`, Vault auth/policies/roles, and KV
entries. Removing or refreshing those management/Vault objects is a separate
privileged operation and is not part of teardown. `teardown-reviewer` can break Vault
logins until the JWT is refreshed through the attended `vault-config` process; do not
run it as cleanup.

Known limitations: local backup is not off-host durable; ingress/DNS and consumer
integration remain environment-specific; and live verification, realm provisioning,
credential rotation, restore drills, network isolation, management-plane approval,
and teardown cannot be honestly claimed from a documentation-only check. Run them
attended against the intended cluster and retain their command output as evidence.
