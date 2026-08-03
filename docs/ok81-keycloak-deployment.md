# OK-81 — Central Keycloak: technical deployment document (phase 1)

> **Language convention:** EN is authoritative for this repository, matching
> `docs/ok-shared-onboarding-guideline.md`.

**Status:** phase 1 has been executed on `ok-shared`. This document holds the **decisions and their
reasons**; authoritative for everything else, under `platform/identity/keycloak/`, are
**`PHASE1-RUNLOG.md`** (what ran, what it returned, every defect found by running it), the **`Makefile` +
`tooling/`** (the procedure — each step below maps to a target) and **`values-ok-shared.yaml`**.

**Scope:** get Keycloak running and verified on `ok-shared`. No ingress, no TLS, no cert decision, no realm
for a real consumer. This document makes no architectural decisions — those live in **ADR-Platform-020**
(Shared Platform Services) and **ADR-Platform-019** (profile-local identity precedent); it sits one level
below, at Implementation Profile and Provider Values. **Tasks:** Jira **OK-81**.

---

## 0. Working copy and change workflow

All changes are made in local clones on a branch and delivered by PR: nothing is edited on a cluster by hand,
nothing is committed straight to `main`, and whoever writes a change is not the person who approves it. Two
repos matter: **`openkubes`** (capability owner: values, database, contract, gate, tooling, runbooks) and
**`ok-cluster`** (consumer: the installer and its `ok-keycloak.ref` pin, phase 2 only).

**The Keycloak chart is a pinned local working copy** at `<workspace>/keycloak`, **detached at tag
`keycloakx-7.2.2`** (verified `name: keycloakx`, `version: 7.2.2`, `appVersion: 26.6.4`), so values are
authored against the real templates and every rendered field is inspectable before anything reaches a
cluster; `require-chart` enforces the exact tag and rejects a modified runtime chart. Being third-party
and pinned it must be excluded from bulk-update routines, and on a Windows mount it needs
`git config core.filemode false`.

**The clone is pruned, and not for tidiness:** upstream ships the **legacy Wildfly chart** beside the current
one, so `helm install ./keycloak/charts/keycloak` is one word away from the chart we deliberately rejected.
It goes, with `charts/mailhog` and upstream CI/governance/release plumbing. **Kept:** `values.schema.json`
(helm validates our values against it on every `template`/`install` — a free correctness check), `LICENSE`,
and `.git`, which pins the tag and proves provenance. The clone therefore reads dirty by design.

**Our changes are values, not chart edits**, and no chart is vendored — neither existing capability does that
(`VaultInstance` pins `vault` 0.30.1, `OpenWebUIInstance` pins `open-webui` 15.2.0, both by reference). A
template that genuinely cannot express what we need becomes an explicit minimal fork delta, argued separately,
at the cost ADR-019's "Fork maintenance" clause documents.

---

## 1. Target — cluster and namespace

| | Value | Why |
|---|---|---|
| **Cluster** | **`ok-shared`** | Fixed by ADR-020 §2. ok-mgmt controls clusters, ok-shared serves them; the guideline's Part A.1 forbids shared services on ok-mgmt. Verified live: 4/4 nodes Ready, Talos v1.9.5, k8s v1.34.1. |
| **Namespace** | **`keycloak`**, for both Keycloak and its database | De facto convention is *namespace = service name* (`vault`, `ingress`, `cert-manager`, `monitoring`, `open-webui`); `NAMING.md` sets no namespace rule, so the existing pattern governs. The DB is Keycloak's private state, not a shared service, so co-locating keeps Secret, PVC and pods under one blast radius and one NetworkPolicy later. The CNPG *operator* stays in `cnpg-system` — a cluster-scoped controller, leave its own convention alone. |
| **Explicitly NOT** | the `vault` namespace | It holds live ADR-025 material (`vault-server-tls`, the CA Issuers, the `IngressRouteTCP`). Writing identity objects there was risk #7 and is avoided by deferring ingress. |

---

## 2. Versions — pinned, verified against the source repo

| Component | Pin | Verified |
|---|---|---|
| Helm chart | `keycloakx` **7.2.2** | Latest tag in `codecentric/helm-charts` (default branch `master`, not archived, updated 2026-07-20). |
| Keycloak image | `quay.io/keycloak/keycloak` **26.6.4**, pinned **by digest** | Chart `appVersion: 26.6.4`; `image.digest` is a first-class chart value, so digest pinning needed no template hacks. Resolved and committed in the values, so the tag cannot move. |
| Chart source | **local path** `<workspace>/keycloak/charts/keycloakx` | Installed from the pruned working copy at tag `keycloakx-7.2.2`, not fetched at install time — the tree rendered and reviewed is the tree applied. |
| PostgreSQL | **16.10**, by digest, via CloudNativePG | Not `16.2` (the RMF comparator's version). CNPG 1.30 supports **14–18**, so 17 is available if we prefer fewer future major upgrades; 16 is the conservative pick against Keycloak 26. A deliberate choice, not drift. |
| CNPG operator | **1.30.x** | Supports Kubernetes **1.34** (ours), 1.35, 1.36 and PostgreSQL 14–18. Released 2026-06-29, EOL ~Dec 2026 — needs an upgrade plan inside six months. 1.29.x also covers 1.34 but ages out 2026-09-29. |

**Rejected, with reasons recorded so it is not revisited:** `codecentric/keycloak` (legacy chart — README states
*"It is no longer maintained"*, appVersion `17.0.1-legacy`, depends on Bitnami PostgreSQL 10.16.2); Bitnami
charts generally (post-Aug-2025 `bitnamilegacy` image hosting); the Keycloak Operator for v1
(`KeycloakRealmImport` creates only, never reconciles, and is undeliverable here since `provider-kubernetes` has
no ok-shared ProviderConfig); raw manifests.

---

## 3. Chart values — the defaults that must be overridden

Read from `keycloakx` 7.2.2 `values.yaml` and its `statefulset.yaml`, not from memory; the applied file is
`values-ok-shared.yaml` and what follows is *why* each override exists.

| Value | Chart default | Ours, and why |
|---|---|---|
| `http.relativePath` | `/auth` (*"for backwards compatibility"*) | **`/`** — left alone we inherit the RMF-era `/auth` prefix into a brand-new platform endpoint |
| `proxy.mode` | `forwarded` → `KC_PROXY_HEADERS` | **`xforwarded`** — `forwarded` is the RFC 7239 header; **Traefik sends `X-Forwarded-*`**. Harmless while we port-forward, wrong the moment ingress lands, so fix it now |
| `dbchecker.enabled` | `false` | **`true`** — wait for PostgreSQL instead of crash-looping into readiness; the ordering discipline ADR-025 criterion 7 made explicit for VSO-before-Helm |
| `command` | `[]`, so the StatefulSet renders **no `command` and no `args` at all** | **`kc.sh start --http-port=8080`** — otherwise the container runs the image's bare entrypoint and never starts the server. Required, not optional. We omit the README's `--hostname-strict=false`, since `KC_HOSTNAME` is explicit and the default is the safer posture; its `KEYCLOAK_ADMIN*` example is stale, predating the `KC_BOOTSTRAP_ADMIN_*` rename |
| `serviceAccount.automountServiceAccountToken` | `true` | **`false`** — Keycloak never calls the Kubernetes API |

**Two images ship here and both are pinned by digest:** `quay.io/keycloak/keycloak` and the `dbchecker` init
container's `docker.io/busybox` — pinning only the first would leave an unpinned image in the release.
`helm template` against the local path is an exact dry run; run it before every install. It confirms the one
thing ADR-024 cares about: **`KC_DB_PASSWORD` as a `secretKeyRef`, never a literal**.

**Two ports, not interchangeable:** `http` **8080** serves the realm and admin console, `http-internal` **9000**
health and metrics (moved to a management port in Keycloak 25+); forwarding the wrong one reads as "Keycloak is
broken".

**Capacity — tighter than it looks.** Every ok-shared node allocates **1950m CPU and ~3.3–3.4 GiB memory** and
three of the four also carry a Vault Raft pod, so the chosen limits take roughly **half a node's CPU and 45% of
its memory** — acceptable once, *not* three times over, which is the practical case against three CNPG instances
independent of the ADR-019 argument. **Cap the JVM heap explicitly:** Keycloak sizes it as a percentage of the
container limit, so a missing limit means sizing against node memory and an OOM kill under load. Postgres gets
explicit requests/limits too; unset on a 3.4 GiB node is how the Vault quorum starts getting evicted.

**Admin bootstrap — the chart wires nothing for you.** It has no admin block at all, so with only database and
hostname values set the StatefulSet renders **no admin environment variable of any kind** and "log in as the
bootstrap admin" would be impossible. Credentials go through `extraEnv` (which accepts full
`valueFrom`/`secretKeyRef` entries) or `extraEnvFrom`; the account is created **once, from an empty database**.

### 3.1 The temporary admin, and why it must actually be replaced

Logged in as the bootstrap admin the console says: *"You are logged in as a temporary admin user. To harden
security, create a permanent admin account and delete the temporary one."* That banner is the acceptance
signal — present immediately after install, **gone** at the end of step 5.

**What drives it — verified, not inferred.** Keycloak stamps the bootstrap account with the user attribute
**`is_temporary_admin: ["true"]`** and renders the banner for whoever holds it; read live, `master` held exactly
one user, `admin`, carrying it. So **deleting the flagged account is the only honest fix**: the attribute is
Keycloak's own record of where that credential came from, and stripping it silences the banner while changing
nothing else — the server stops reporting a true fact about itself, and the trail reads as a bootstrap account
with a hand-edited flag. Considered and rejected on those grounds. A rename does not clear it either — the
attribute follows the account, not the name.

**Usernames — the permanent account is `admin`, and the temporary one already owns that name.**
`KEYCLOAK_ADMIN_USERNAME` drives both the seeded `username` and `KC_BOOTSTRAP_ADMIN_USERNAME`, so the temporary
admin is created *as* `admin`. Usernames are unique per realm, and the safe order (create permanent → verify →
*then* delete temporary) needs both to exist at once — so the cutover frees the name by renaming the temporary
account to `bootstrap-admin` for the seconds before deleting it. That rename needs `editUsernameAllowed`, which
`master` ships as `false` and which marks `username` read-only **in the admin REST API too**, not just
self-service: a rename returns `400 error-user-attribute-read-only` until it is on. The cutover turns it on,
renames, then restores and re-reads it — on the failure path too, so an aborted run cannot leave the realm more
permissive than it was found.

**Reusing the existing KV path is deliberate.** A separate `…/keycloak/admin-permanent` path was the first
design and is worse: the account is called `admin` either way, and the `VaultStaticSecret` →
`keycloak-admin` → `make verify` chain already reads `…/keycloak/admin`. Writing the permanent credential
there bumps its version and leaves every consumer working; a second path meant a second VSS and a stale
first one.

**Rotation — the two credentials behave differently, and Vault cannot rotate one of them at all.** The **admin
account** changes only through Keycloak's own API or console, Vault updated afterwards as escrow: **changing
the Vault value alone never changes an existing Keycloak account**, because it lives in the database and the
bootstrap variables are read only when no admin exists. The **database role** is the opposite — but only
because `spec.managed.roles[].passwordSecret` is wired; **without** it, rotation means quiescing Keycloak,
`ALTER ROLE … PASSWORD`, writing the same value to Vault, then restarting. Step 5 items 5–6 exercise both.

### 3.2 TLS shape — decided: passthrough, Keycloak serves its own certificate

Settled rather than left open, because it determines values and therefore what phase 2 pins.
Reachability for ok-shared is **192.168.100.207:443** (MetalLB on the *infra* cluster) → Traefik →
**TLS passthrough** to the service. Keycloak follows that path, exactly as Vault already does: TLS is
end-to-end, with no plaintext hop into ok-shared. Three consequences, none of them cosmetic:

**Tested on ok-shared, not merely decided** (2026-08-03). A certificate was issued from
`ClusterIssuer/ok-shared-internal-ca`, mounted, and Keycloak brought up serving
`http://0.0.0.0:8080` **and** `https://0.0.0.0:8443`. A client using SNI `keycloak.ok-shared.internal`
and the internal CA got `http=200` on the discovery document with `ssl_verify_result=0` /
`Verify return code: 0 (ok)`. So a passthrough backend works, and the certificate story is solved. The
configuration was rolled back afterwards because phase 1 has no ingress; three findings survive it:

- **Enabling server TLS flips the MANAGEMENT port to HTTPS too** — the log says
  `Management interface listening on https://0.0.0.0:9000`. The chart's health probes speak HTTP to
  that port, so they fail and the pod never becomes ready. `http.internalScheme: HTTPS` is the knob,
  and it is easy to miss because nothing about it mentions probes.
- **Discovery advertised `issuer: http://localhost:8080/realms/master` while being served over HTTPS.**
  That is the `KC_HOSTNAME` coupling made visible: no OIDC client would accept it. The hostname flip is
  mandatory, not cosmetic.
- **Keycloak serves both protocols at once**, so the migration can be staged rather than cut over:
  add HTTPS, then flip `KC_HOSTNAME` and rework the conformance origin, then add the route.

1. **Keycloak needs its own server certificate** — now trivial, from
   `ClusterIssuer/ok-shared-internal-ca`, with SAN `keycloak.ok-shared.internal`. The chart has no
   `tlsSecret` value, so it is wired like Vault's: mount the cert Secret through `extraVolumes` and
   point `KC_HTTPS_CERTIFICATE_FILE`/`KC_HTTPS_CERTIFICATE_KEY_FILE` at it. `service.httpsPort` is
   already `8443`.
2. **`proxy.mode: xforwarded` must be REMOVED, and this one is security-relevant.** §3 sets it because
   a *terminating* edge sends `X-Forwarded-*`. Under passthrough nothing does — so trusting those
   headers would let any client set its own apparent source IP, protocol and host. The phase-1
   override is correct for phase 1 and wrong the moment passthrough lands; it inverts.
3. **`KC_HOSTNAME` becomes `https://keycloak.ok-shared.internal`**, which is incompatible with the
   port-forward origin the phase-1 conformance suite depends on. `require-values-contract` asserts that
   coupling deliberately, so it changes with this, not before.

**Not applied in phase 1**, and that is the point of writing it down: phase 1 has no ingress by
decision, and the current verified flow depends on `http://localhost:8080`. Implementing TLS now would
break a working, verified system to no benefit.

**One tension to resolve in an ADR, not here.** ADR-010's "standard `Ingress` +
`ingressClassName: ok-ingress`" reads as edge *termination*, while the platform's actual reachability
is passthrough — which needs a Traefik `IngressRouteTCP`, the very thing ADR-019 §5 records as
transitional profile debt. Vault is already in that position. Either ADR-010 accommodates passthrough
for TLS-sensitive backends, or Keycloak terminates at the edge and diverges from Vault. That is an
architectural decision and this document makes none.

---

## 4. Sequence

Every step is a Makefile target (`make help`), each naming its own verification. Stop at the first failure. The
order is not arrangeable — each step consumes what the previous one produced. **Step 0** (`baseline`) captures
Vault's health and certificate as a known-good reference; nothing in phase 1 should touch Vault, which is
exactly why it is worth having. **Step 1** (`install-vso`) *enumerates first* — every existing
`VaultConnection`/`VaultAuth`/`VaultStaticSecret` — because starting the operator reconciles everything at once
and a non-empty list changes the plan.

**Who owns the PostgreSQL password — resolved. Vault owns the desired value; PostgreSQL remains the runtime
authority that validates it.** One Secret, `keycloak-db`, materialised by VSO as `kubernetes.io/basic-auth`,
wired in three places and nowhere else: CNPG bootstrap (`initdb.owner`/`initdb.secret.name`), CNPG ongoing
(`spec.managed.roles[keycloak].passwordSecret` — **without this, changing the Vault value later does not
rotate the role**), and Keycloak (`database.existingSecret`). Do **not** also use CNPG's generated
application Secret, and do **not** let CNPG and VSO both manage it — VSO owns it, CNPG reads it; if they
disagree the symptom is `password authentication failed` and `CrashLoopBackOff`. Hence the CNPG cluster is
created *after* the Secret exists: its bootstrap consumes it.

**Step 2 — credentials via the Vault path (decided).** No hand-seeding: Keycloak is the first real
consumer of the scoped seeding identity OK-115 delivered, and hand-seeding would leave an unaccounted
credential inside the one service whose job is accounting for identity.

**Two identities, not one.** `seedRoles` grants **write only**, deliberately, so VSO cannot read what the
seeder writes — a `VaultStaticSecret` backed by the seeder never syncs. The `VaultConfig` must *also*
carry an ordinary `roles[]` entry granting **read** on `secret/data/ok-shared/keycloak/*`, bound to a
dedicated VSO reader SA. This mirrors the split `ok-obs-verify` uses (`sa-obs` reads, `vault-seed-obs`
seeds).

1. **Identities first:** namespace, a dedicated **reviewer** SA with `system:auth-delegator`, the **seeder**
   SA, and a separate **VSO reader** SA — before the XR, so TokenReview capability and identities exist, and
   with VSO already running so no CR sits inert. Do **not** reuse the Vault chart's `vault-server-binding` as
   the reviewer: ADR-025 wants a dedicated Category-A identity. **The reviewer JWT is not automatic** —
   Kubernetes 1.34 creates no long-lived SA token Secret, and without one **every** seeder and VSO login
   fails at TokenReview, presenting as a policy problem it is not; create an explicit
   `kubernetes.io/service-account-token` Secret annotated `kubernetes.io/service-account.name`. A projected
   token instead? This cluster enforces a **10-minute minimum**: `--duration=300s` yields an empty token,
   previously misread as lost policy.
2. **Apply the `VaultConfig` XR** on ok-mgmt with the ok-shared CA, the reviewer JWT ref, **and both** a
   `seedRoles` entry for `appName: keycloak` and the read `roles[]` entry above. **This targets ok-mgmt and
   is privileged: `--dry-run=server` first, review, explicit approval before the real apply — every time.**
   It is the one step that writes into the live Vault other clusters already depend on. Then **wait for
   convergence, not for the apply to return**: the XR *and* the provider-vault managed resources must report
   `Ready=True` **and** `Synced=True`, because seeding against an unconverged auth mount fails confusingly.
3. **Seed as the seeder SA**, never in argv, with a create/update write — **never `kv patch`**, which is
   read-modify-write and the seeder has no read. Use `options.cas=0` so the write is an atomic create rather
   than a silent overwrite. Then create `VaultConnection`/`VaultAuth` and both `VaultStaticSecret` objects and
   wait for a **current** successful sync (see the gate below).

   > **The derived policy glob requires a sub-path.** The Composition emits
   > `path "secret/data/<cluster>/<app>/*"`, and `…/keycloak/*` does **not** match `…/keycloak` itself. The
   > first attempt wrote to the app root and got a flat `permission denied` that looks identical to a
   > misconfigured role. One sub-path per consumer Secret, mapping 1:1 onto the Kubernetes Secrets:
   > `…/keycloak/admin` → `keycloak-admin`, `…/keycloak/db` → `keycloak-db`.

**Step 3's database** is one `Cluster`, `instances: 1`, PostgreSQL 16, `storageClass: local-path`, explicit
storage/requests/limits, bootstrapping from the **already-materialised** `keycloak-db` Secret. `local-path` is
`WaitForFirstConsumer` with reclaim **`Delete`** — a deleted PVC destroys realm state, which is why the backup
step is not optional. **Step 4 installs from the local chart path**, never a registry fetch, so the exact tree
rendered and reviewed is the tree applied; provenance is the tag `keycloakx-7.2.2` enforced by
`require-chart`, plus the digests committed in the values.

**The gate between them — assert the right condition on the right object**, because a wait on the wrong
condition is worse than no wait. Each `VaultStaticSecret`: `SecretSynced=True` **for the current
`metadata.generation`**, with the expected destination Secret and keys — not mere Secret existence, and not a
stale success from an earlier generation. Then the CNPG `Cluster`: `Ready=True`, not pod readiness.

**The three start-order failures are all recoverable**, and crucially none creates an admin against the
wrong credential. A **missing** Secret gives `CreateContainerConfigError` — no Keycloak code runs, database
untouched. A **wrong password** starts, fails DB auth and crash-loops; it can neither migrate nor create the
bootstrap admin because it never gets a session, and recovery needs the pod **recreated**, since
Secret-backed env vars do not update in a running container. **Postgres not yet accepting connections**
self-heals on CNPG readiness. A half-applied migration is a different mode — it needs a connection to succeed
and *then* fail mid-migration — and is why the backup step exists.

**Step 5 — functional verification over `kubectl port-forward`** (the guideline's own pattern for
Central Grafana: *"port-forward for now; ingress per ADR-010 is a follow-up"*):

1. Discovery document served and its `issuer` matches `KC_HOSTNAME` exactly — the check that catches a
   wrong hostname/proxy configuration early. In phase 1 that value *is* `http://localhost:8080`, because
   the port-forward is the only way in and a token issued under any other origin would be a lie;
   `require-values-contract` asserts the values and the port-forward agree, and `verify` refuses to run if
   something else already holds the port. Changing this to the real hostname is part of the ingress work,
   not a fix to make here.
2. Admin console reachable; log in with the bootstrap admin and **record that the temporary-admin banner is
   displayed** — it is the before-state of item 5 and cannot be asserted as removed if never observed present.
3. A **neutral conformance realm** and confidential client — not `ok2-rmf`, whose kubeconfig fails TLS
   verification today, and a repo template is not confirmation of a live cluster's redirect URIs.
4. **Authorization-code + PKCE** end to end with expected claims — the guarantee that justifies a central IdP,
   which client-credentials alone does not prove — then a client-credentials grant whose JWT verifies against
   the advertised JWKS. Then restart the Keycloak pod, and the database pod: realm and client survive both.
5. **Permanent-admin cutover — the banner must be gone** (`make admin-cutover`). Assert exactly one account
   carries `is_temporary_admin` and owns the wanted name; rename it (§3.1); create `admin` with the `master`
   realm role `admin`; **verify before anything destructive** — authenticates, can list realms, carries no
   temporary flag; **escrow to `…/keycloak/admin` and log in with the materialised Secret**; only then
   delete the temporary account, using the permanent admin's own token so its power is proven by the act;
   finally assert `master` users == `[admin]`, no account carries the flag, and the old password is refused.

   **Escrow before delete, not after** — load-bearing. The first implementation escrowed last; a wrong
   assertion aborted the run and the generated password existed nowhere but a work directory the script's own
   cleanup trap deleted, locking the console out. With escrow first, the worst case of any later failure is a
   half-finished cutover in which **both** accounts still work. Two details that produced false failures:
   a rejected password grant answers **`400` with `error=invalid_grant`**, not `401` (401 is *client*
   authentication failure); and work directories holding generated credentials must not be
   auto-deleted. **Break-glass** (`make recover-admin`) is Keycloak's own `kc.sh bootstrap-admin user` run
   inside the live pod — a fresh temporary admin written straight to the database, no restart, no data loss,
   password escrowed *before* the account exists. It needs `KC_HTTP_PORT`/`KC_HTTP_MANAGEMENT_PORT` overridden
   or the partial server it boots hits `Address already in use`. What it creates is itself temporary, so
   recovery is always followed by a cutover.
6. **Rotation lifecycle — exercised, not described** (`make rotation-test`), because the §3.1 asymmetry is a
   claim until it has been made to fail and succeed once. The **admin account**: rotate through Keycloak's
   API → new works, previous refused; then the two negatives that carry the argument — the Vault-materialised
   Secret still holds the **old** value and **no longer authenticates**, and a value written to **Vault
   alone** does **not** authenticate while Keycloak keeps accepting only what its own API set — then
   converge and re-verify via the Secret. The **database role**: write to `…/keycloak/db` → wait for the
   destination Secret → assert CNPG reconciled mechanically, on
   `status.managedRolesStatus.passwordStatus.keycloak.resourceVersion` **advancing** → `psql` accepts the new
   value and **refuses** the old → recreate the Keycloak pod → Ready, discovery served, admin login works.
   Secret-backed env vars do not change in a running container, so that restart is what proves the credential
   works for the *consumer* and not merely for `psql`.

   Two gates that look right and are not: **`SecretSynced=True` cannot gate a rotation** — after a Vault
   write the VSS generation is unchanged, so it is *already* true and says nothing about the new value;
   compare the destination Secret's value instead (by comparison, never by printing either side). And
   **assert the reason, not just the failure** — an unreachable server and a rejected password both fail, so
   the database negative requires the error to contain `password authentication failed`.

**Step 6 — the Vault post-check.** Re-run step 0's probes, and split the claim, because "the Vault baseline is
unchanged" is ambiguous in a dangerous way. **Reachability and TLS must be unchanged** —
`vault.ok-shared.internal` still resolving to Vault's own certificate (not Traefik's), SNI route matching,
authenticated health answering; phase 1 adds no route, so this should be a no-op, and a no-op actually
executed is the only way to state it. But **Vault's configuration is deliberately NOT unchanged**: step 2
adds the `auth/kubernetes/ok-shared` mount, the `okvc-ok-shared-keycloak-seed` policy, an `AuthBackendRole`
and KV entries under `secret/data/ok-shared/keycloak/`. Enumerate those and assert **nothing else** changed —
no pre-existing `okvc-*` policy, no other cluster's mount, no `ok-admin`/`ok-config-automation` policy — conflating the two lets a real regression hide
behind a green reachability check.

---

## 5. Rollback

`helm uninstall`, delete the CNPG `Cluster`, then the namespace. The PVC is `reclaim: Delete`, so **realm
state is destroyed** — acceptable in phase 1 precisely because no real consumer exists yet. Nothing else on
ok-shared is touched: no CA, no Issuer, no Traefik route, no Vault object. VSO and the CNPG operator stay
(additive controllers); remove VSO only after confirming nothing else depends on it. Teardown deliberately
retains the ok-mgmt reviewer JWT, the `VaultConfig` XR, Vault auth/policies/roles and KV entries — so a
rebuild reuses the existing admin credential rather than minting one, which also means it comes back with a
*temporary* admin and needs the step-5 cutover re-run.

---

## 6. Deliberately not in phase 1

Named with its actual blocker, because "not in phase 1" hides the difference between *can't yet* and *haven't*.

| Deferred | Blocker — verified on ok-shared |
|---|---|
| Ingress + TLS (standard `Ingress`, `ingressClassName: ok-ingress` per ADR-010 — **not** a Traefik `IngressRoute`, which ADR-019 §5 records as transitional profile debt) | The mechanism is ready: IngressClass `ok-ingress` (Traefik) exists. The certificate half is now **resolved**: `ClusterIssuer/ok-shared-internal-ca` exists and is `Ready` ("Signing CA verified"), reusing the CA ADR-025 already established rather than minting a second trust root, and a probe Certificate for `keycloak.ok-shared.internal` was issued from the `keycloak` namespace and verified to chain to it. What still blocks is **DNS only**: nothing under `.internal` resolves. Reachability itself is fine and ok-shared deliberately runs no MetalLB of its own — external clients arrive at **192.168.100.207:443** (MetalLB on the *infra* cluster) → Traefik → TLS passthrough, so a `<pending>` LoadBalancer IP on ok-shared is expected rather than broken. Names are pinned to that IP for now; the follow-up is **OK-57**, whose real scope is the Multus/vSwitch interface that makes `.internal` names reachable — for the API-server path a CoreDNS `hosts` entry on ok-mgmt suffices and does not wait on it. The passthrough shape and its values consequences are settled in §3.2 |
| Metrics scraping | Keycloak already serves metrics on 9000, and there is no local `monitoring` namespace **by design** — central monitoring is the **`ok-observability`** capability. So this is a registration against that capability's contract, not a stack to stand up here, and `ok-observability/AGENTS.md` binds any change to it (`make verify`, `make conformance` **and** `make evidence` before proposing anything) |
| The ok-cluster installer, its Makefile target and `ok-keycloak.ref` | Nothing on the `openkubes` side is merged yet, and `.ref` pins a *consumed revision*, so this cannot be written before the capability lands. `ok-observability.ref` is the pattern to copy |
| A real consumer realm | No consumer has asked yet; the conformance realm proves the flows without inventing one |
| Central OIDC default-on in a per-cluster stack | ADR-020 §4 requires opt-in; changing it is a contract touch needing an ADR amendment |

**Undone rather than blocked — nothing external is missing for these:**

- **`pg_dump` backup and a restore drill** — `pg_dump` is already in the CNPG pod, so no new dependency, and it
  is the highest-value gap: the PVC is `reclaim: Delete` and this document calls the backup "not optional".
- **Retiring the bootstrap env wiring** — `extraEnv` still carries `KC_BOOTSTRAP_ADMIN_*` and
  `require-values-contract` asserts they are present, so an empty database would mint a temporary admin again,
  the exact thing §3.1 removed. Values + contract change + Helm upgrade, with `recover-admin` as the escape hatch.
- **Brute-force protection** — `master` reports `bruteForceProtected: false`; one realm setting.
- **NetworkPolicy** — Cilium is present and the namespace holds one workload plus its database, so the policy is
  small, but it can silently break VSO and CNPG traffic and needs its own verify step.

The chart also ships Gateway API `HTTPRoute` support and a console-only route, worth remembering for ADR-010
v2 — ADR-019 §5 already flags Gateway API as the cleaner fit for path rewriting.
