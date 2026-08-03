# OK-81 phase 1 — run log (2026-07-31)

Every command actually executed, in order, with what it verified. This was the source for the
`Makefile` that now sits beside it: each block below maps to one target, and each has a teardown
counterpart. **Read "Cycle defects" at the end before trusting any target here** — six of them
were only found by tearing the deployment down and rebuilding it.
Nothing here is aspirational — if a command is listed, it ran and its stated result is what it
returned. `CLUSTER=ok-shared`, `NAMESPACE=keycloak`, `KUBECONFIG=~/.kube/ok-shared.yaml`.

Variables the Makefile owns (never inline literals):
`CLUSTER`, `NAMESPACE`, `VAULT_NS=vault`, `VSO_NAMESPACE=vault-secrets-operator`,
`VSO_CHART_VERSION=1.5.0`,
`CHART_DIR=<workspace>/keycloak/charts/keycloakx`, `CHART_TAG=keycloakx-7.2.2`,
`CNPG_MANIFEST=<workspace>/cnpg/releases/cnpg-1.30.0.yaml`, `CNPG_TAG=v1.30.0`.
`VAULT_HOST`/`VAULT_LB` are the EXTERNAL consumer endpoint and default to **empty** — they are
environment-specific and not discoverable from this cluster. See Cycle defect 6.

---

## Target `baseline` (step 0) — read-only, no teardown
Capture Vault's pre-change state so the post-check can be the same probes, not a different claim.

    # 1. the endpoint every consumer uses is reachable
    bash -c 'cat < /dev/null > /dev/tcp/$(VAULT_LB)/443'

    # 2. public CA only — never the key
    kubectl get secret vault-server-tls -n $(VAULT_NS) \
      -o jsonpath='{.data.ca\.crt}' | base64 -d > $(CA_FILE)
    openssl x509 -in $(CA_FILE) -noout -subject -issuer -dates

    # 3. which certificate is actually served for that SNI
    echo | openssl s_client -connect $(VAULT_LB):443 -servername $(VAULT_HOST) \
      -CAfile $(CA_FILE) 2>/dev/null | openssl x509 -noout -subject -issuer -dates -ext subjectAltName
    echo | openssl s_client -connect $(VAULT_LB):443 -servername $(VAULT_HOST) \
      -CAfile $(CA_FILE) 2>&1 | grep -E 'Verify return code'

    # 4. unauthenticated health through that same path
    curl -s -o health.json -w '%{http_code}' \
      --resolve $(VAULT_HOST):443:$(VAULT_LB) --cacert $(CA_FILE) \
      https://$(VAULT_HOST)/v1/sys/health

    # 5. quorum: all three peers must agree on the committed index
    for p in vault-0 vault-1 vault-2; do \
      kubectl exec -n $(VAULT_NS) $$p -- vault status -format=json ; done

**Observed:** TCP open. CA `CN=ok-shared-internal-ca`, valid to 2036-07-22. Served cert
`CN=vault.ok-shared.internal` issued by that CA, valid to 2027-07-25, SAN includes
`vault.ok-shared.internal`, `vault-active*`, `*.vault-internal`, `localhost`, `127.0.0.1`;
`Verify return code: 0 (ok)` — i.e. **Vault's own certificate, so TLS passthrough is intact**.
Health `http=200`, `initialized=true sealed=false standby=false`, version `1.20.1`, cluster
`vault-cluster-a6e38fd1`. All three pods `sealed=false ha_enabled=true`,
`raft_committed_index` identical at **82185**, 0 restarts, one per worker node.

**Assertion for the Makefile:** fail unless http==200, the served issuer is
`CN=ok-shared-internal-ca`, the subject CN is the Vault host (not a Traefik default cert), verify
code is 0, and all three committed indices are equal. Index *equality* is the check — the value
advances normally.

---

## Target `install-vso` (step 1) — teardown: `helm uninstall` + namespace, CRDs left in place
Enumerate before activating: starting the operator reconciles every pre-existing CR at once.

    # 1. every VSO kind, cluster-wide, must be empty before the operator runs
    for k in vaultconnections vaultauths vaultauthglobals vaultstaticsecrets \
             vaultdynamicsecrets vaultpkisecrets hcpauths hcpvaultsecretsapps \
             secrettransformations csisecrets; do \
      kubectl get $$k.secrets.hashicorp.com -A --no-headers ; done

    # 2. provenance of the pre-existing CRDs (are they helm-managed? is there a stale release?)
    kubectl get crd vaultstaticsecrets.secrets.hashicorp.com -o json
    kubectl get ns | grep -iE 'vault-secrets|vso'
    kubectl get secret -A --field-selector type=helm.sh/release.v1 --no-headers | grep -i vso
    kubectl get clusterrole,clusterrolebinding --no-headers | grep -c vault-secrets-operator

    # 3. install through ok-cluster's own target — do not hand-roll the helm command
    make -C $(OK_CLUSTER) install-vso CLUSTER=$(CLUSTER)

**Observed:** all ten kinds empty. CRDs created 2026-07-25 with no helm labels, no VSO namespace,
no VSO helm release, 0 VSO cluster RBAC objects — applied bare, operator had never run, so no
stale reconcile was possible. Install: `Release "vault-secrets-operator" does not exist.
Installing it now.` → **REVISION 1**, `STATUS: deployed`, `--wait` satisfied, `MAKE_EXIT=0`.
Post: controller-manager `Running`, containers `true,true`, restarts `0,0`; CRDs
`NamesAccepted=True Established=True`; VSO CRs still zero; namespace PSA labels
`enforce/warn/audit=baseline`.

**Read the make exit code from `PIPESTATUS`, never from a trailing `echo`** — a backgrounded
compound command's `echo "exit=$?"` reports the echo's status and has masked a real failure here.

---

## Target `identities` (step 2.1) — teardown: delete the namespace ONLY; the reviewer is RETAINED (see Cycle defect 2)
Applied from one manifest, ordered so the namespace precedes its ServiceAccounts.

    kubectl apply --dry-run=server -f $(MANIFESTS)/identities.template.yaml
    kubectl apply -f $(MANIFESTS)/identities.template.yaml

Objects: namespace `keycloak`; SA `kube-system/vault-reviewer`; ClusterRoleBinding
`vault-reviewer-tr` → `system:auth-delegator`; Secret `kube-system/vault-reviewer-token`
(type `kubernetes.io/service-account-token`, annotated to that SA); SA `keycloak/sa-keycloak`
(VSO reader); SA `keycloak/vault-seed-keycloak` (seeder).

**Note on the dry run:** it reports `namespaces "keycloak" not found` for the two SAs inside the
new namespace. That is a server-dry-run limitation, not a manifest error — the real apply creates
the namespace first. A Makefile must not treat that dry-run output as a failure.

Verification, positive **and** negative:

    kubectl get secret vault-reviewer-token -n kube-system -o json        # token populated?
    kubectl auth can-i create tokenreviews.authentication.k8s.io \
      --as=system:serviceaccount:kube-system:vault-reviewer               # expect yes
    kubectl auth can-i create subjectaccessreviews.authorization.k8s.io \
      --as=system:serviceaccount:kube-system:vault-reviewer               # expect yes
    kubectl auth can-i list secrets -n keycloak \
      --as=system:serviceaccount:keycloak:vault-seed-keycloak             # expect no
    kubectl auth can-i create tokenreviews.authentication.k8s.io \
      --as=system:serviceaccount:keycloak:sa-keycloak                     # expect no

**Observed:** token Secret populated by the controller — keys `ca.crt`, `namespace`, `token`,
token 1271 bytes. Reviewer: `yes` to both reviews. Seeder: `no` to listing secrets. `sa-keycloak`:
`no` to tokenreviews. So the reviewer capability exists and neither workload identity has it.

**The negatives matter as much as the positives.** A target that asserts only "reviewer can
review" would pass just as happily if every SA were cluster-admin.

---

## Post-change Vault re-check (run after every mutating target)
Same probes as `baseline`, compared field by field.

**Observed after `install-vso` and `identities`:** health `http=200` with
`initialized/sealed/standby/version/cluster_name` all identical to baseline; served certificate
still `CN=vault.ok-shared.internal` issued by `CN=ok-shared-internal-ca`; all three peers
`sealed=false ha=true` with `raft_committed_index` identical at **82238** (advanced from 82185 —
normal progress; equality is the invariant).

---

## Everything above has now been executed, twice
Phase 1 ran manually first, then twice more end-to-end through `make teardown` + `make install`.
The manual run is what this log records step by step; the Makefile targets were transcribed from
it and then corrected by what the cycles exposed (see "Cycle defects" at the end).

## Teardown order (reverse of create) — now implemented as `make teardown`
Helm release → CNPG `Cluster` (PVC is reclaim `Delete`: realm state is destroyed) →
`VaultStaticSecret`/`VaultAuth`/`VaultConnection` → namespace `keycloak` → ClusterRoleBinding
`vault-reviewer-tr` → `kube-system` SA + token Secret → VSO release and namespace.
Vault-side objects (auth mount, policies, roles, KV entries) are **not** removed by any of this:
they live on ok-mgmt's `VaultConfig` XR and in Vault, and the seeder deliberately cannot delete KV.
Removing those is a separate, privileged decision — do not let a `teardown` target imply it.

---

## Target `vault-config` (steps 2.3 + 2.4) — teardown: delete the XR, then the reviewer JWT Secret
Two gated applies against **ok-mgmt**, in this order. Both need explicit approval.

    # a. copy the reviewer JWT from ok-shared into crossplane-system ON OK-MGMT.
    #    The XR's reviewerJwtSecretRef points at ok-mgmt, not at the consumer cluster.
    #    Never --from-literal: that puts the JWT in argv.
    umask 077; d=$(mktemp -d); trap 'rm -rf -- "$d"' EXIT
    kubectl --kubeconfig $(SHARED_KUBECONFIG) get secret vault-reviewer-token -n kube-system \
      -o jsonpath='{.data.token}' | base64 -d > $$d/token
    kubectl create secret generic ok-shared-reviewer-jwt -n crossplane-system \
      --from-file=token=$$d/token --dry-run=client -o yaml | kubectl apply -f -

    # b. the XR itself
    kubectl apply --dry-run=server -f $(VAULT_EXAMPLES)/ok-shared-vaultconfig.yaml
    kubectl apply -f $(VAULT_EXAMPLES)/ok-shared-vaultconfig.yaml

**Observed:** Secret created with a `token` key (1271 bytes staged). XR created;
`Synced=True Ready=False` at t+10s, `Ready=True` at **t+20s** — so a Makefile must *wait*, not
assume. Six managed resources, all `True/True`: `Backend kubernetes/ok-shared`,
`AuthBackendConfig auth/kubernetes/ok-shared/config`, `AuthBackendRole …/role/sa-keycloak`,
`AuthBackendRole …/role/keycloak-seed`, `Policy okvc-ok-shared-sa-keycloak`,
`Policy okvc-ok-shared-keycloak-seed`. Rendered bodies:

    okvc-ok-shared-sa-keycloak    path "secret/data/ok-shared/keycloak/*" { capabilities = ["read"] }
    okvc-ok-shared-keycloak-seed  path "secret/data/ok-shared/keycloak/*" { capabilities = ["create","update"] }

**Guards proven able to fail** (server dry-run, three deliberately broken variants):
seed role reusing the workload SA → DENIED by CEL; `appName: keycloak/other` → DENIED by pattern;
seed `ttlSeconds: 3600` → DENIED by the 600s cap. A green dry-run alone would not have shown this.

**Pin:** `compositionRevisionRef: vaultconfig.platform.openkubes.ai-47f7223` with
`compositionUpdatePolicy: Manual` — revision 9, the one `ok-obs-verify` already runs with a working
`seedRoles` pair. Verified live before pinning, not assumed.

---

## Target `seed` (step 2.5) — no teardown: the seeder deliberately cannot delete
Script: `ok81-seed.sh` (to be committed under the capability's tooling).

**The trap, and it cost one failed run.** The derived policy is
`path "secret/data/<cluster>/<app>/*"`. That glob does **not** match the app root
`secret/data/ok-shared/keycloak`, so the first write returned a flat `permission denied` —
indistinguishable from a broken role. Seed **sub-paths**:

    secret/data/ok-shared/keycloak/admin   -> username, password  (Secret keycloak-admin)
    secret/data/ok-shared/keycloak/db      -> username, password  (Secret keycloak-db)

Sequence: generate two independent 32-byte passwords → `kubectl create token vault-seed-keycloak
-n keycloak --duration=600s` (below the cluster's 10-minute minimum the token comes back empty) →
POST `auth/kubernetes/ok-shared/login` with role `keycloak-seed` → write each sub-path with
`options.cas=0`. Every credential travelled in a 0600 file or a `curl --config` file; none in argv.

**Observed:** login returned exactly `['okvc-ok-shared-keycloak-seed']`, ttl 600. Both writes
returned **version 1** (cas=0 ⇒ they did not pre-exist). Negatives: read-back **403**,
cross-cluster write to `secret/data/ok-robotics/obs/probe` **403**. `RESULT: PASS`, exit 0.

**For the Makefile:** this target is not idempotent by design — a re-run with `cas=0` fails
because the path now exists. That is correct behaviour, not a bug: re-seeding is a rotation, which
is a different operation with different consequences. A `seed` target must say so rather than
silently switching to an overwrite.

---

## Vault re-checked after every mutation above
`sys/health` 200 with all baseline fields identical; certificate still Vault's own; quorum in sync
(82238 → 82975, equal across all three peers). `ok-obs-verify` and `ok-robotics` XRs both still
`True/True` — untouched throughout.

---

## Target `vso-wiring` (step 2.6) — teardown: delete the four objects, then the vault-ca Secret
CA (public cert) copied into `keycloak` first: `caCertSecretRef` is a Secret **name**, resolved in
the VaultConnection's own namespace — it cannot point at `vault/vault-server-tls` cross-namespace.

Objects: `VaultConnection vault` → `https://vault-active.vault.svc.cluster.local:8200` (in-cluster:
Vault is in this cluster, so no hairpin out to MetalLB/Traefik; the server cert SAN already covers
that name, verified in the baseline). `VaultAuth keycloak` → mount `kubernetes/ok-shared`, role and
SA `sa-keycloak`, `tokenExpirationSeconds: 600`. Two `VaultStaticSecret` reading
`ok-shared/keycloak/{admin,db}`.

**`automountServiceAccountToken: false` does not affect VSO** — its ClusterRole holds
`serviceaccounts/token: create`, so it mints tokens via TokenRequest rather than reading a mounted
one. Checked, not assumed.

**Gate:** `SecretSynced=True` AND `status.lastGeneration == metadata.generation`. Satisfied at
t+8s, gen=2 lastGen=2 on both. On VSO 1.5.0 `SecretSynced` **is** a real condition type — observed
directly, contrary to a review claim that it is only an Event reason.

**Observed:** `keycloak-db` is type `kubernetes.io/basic-auth`, `username=keycloak` (matches the
role), label `cnpg.io/reload=true`, non-empty password — all three CNPG requirements met.
`keycloak-admin` is Opaque with username/password. Both carry VSO's `_raw` key, which is harmless.

---

## Target `database` (step 3) — teardown: delete the Cluster (PVC reclaim Delete destroys state), then the operator
CNPG **v1.30.0**, installed from a local pinned clone at tag `v1.30.0`, never fetched at apply time.
Provenance: the in-tree `releases/cnpg-1.30.0.yaml`, the GitHub release asset and the raw
release-1.30 branch **all三 agree** on sha256 `f8bede43…`. Note the published checksums file covers
only the `kubectl-cnpg` plugin binaries — there is **no** upstream checksum for the operator YAML,
so triple-source agreement is the available provenance, not a signature.

    kubectl apply --server-side --force-conflicts -f cnpg/releases/cnpg-1.30.0.yaml

**`--server-side` is required, not stylistic.** A plain `kubectl apply` fails on
`clusters.postgresql.cnpg.io` and `poolers.postgresql.cnpg.io` with
`metadata.annotations: Too long: may not be more than 262144 bytes` — the last-applied-configuration
annotation cannot hold CRDs that size. The Deployment and webhooks apply fine, so a partial install
results, which leads directly to the next trap.

**Trap, hit for real:** the operator pod started before those two CRDs existed and crash-looped with
`no matches for kind "Cluster" in version "postgresql.cnpg.io/v1"` — its discovery cache is built at
startup. Fix once the CRDs are Established: `kubectl rollout restart deployment/cnpg-controller-manager
-n cnpg-system`. A Makefile must therefore wait for CRD `Established=True` **before** the operator
Deployment is considered, or restart it afterwards.

Cluster: `keycloak-db`, 1 instance, PostgreSQL `16.10-system-trixie` **pinned by digest**
`sha256:26e146bc…`, 10Gi `local-path`. Phases observed: `Setting up primary` → `Waiting for the
instances to become active` → `Cluster in healthy state ready=True 1/1` at **t+50s**. PVC Bound.

**The ownership model is proven end to end, not assumed:**
- `managedRolesStatus.byStatus.reconciled: ["keycloak"]`, and
  `secretsResourceVersion.managedRoleSecretVersion.keycloak-db` matches the Secret's resourceVersion.
- A real login with the Vault-sourced password (piped via stdin, never argv) returned
  `keycloak|keycloak` from `select current_user, current_database()`.
  Vault → seeder write → VSO read → Secret → CNPG bootstrap → PostgreSQL authentication.

---

## Correction to the `baseline` assertion above
Earlier this log said the Makefile should fail unless all three `raft_committed_index` values are
**equal**. That is too strict and would produce false failures: the three `vault status` calls are
issued sequentially, seconds apart, so a healthy cluster legitimately reports e.g.
`83621 83638 83638`. The correct assertion is that every peer is unsealed with `ha_enabled=true`,
and that the indices are close and advancing between runs — not byte-equal within one run.

---

## Target `keycloak` (step 4) + `verify` (step 5) + `post-check` (step 6)

**Step 4 — install from the LOCAL chart path.** Both images pinned by digest before install
(`quay.io/keycloak/keycloak@sha256:0aae0de7…`, `docker.io/busybox@sha256:9532d8c3…`); the render
confirmed no mutable tag survives. `helm upgrade --install keycloak ./keycloak/charts/keycloakx
-n keycloak -f …/values-ok-shared.yaml` → REVISION 1, deployed, exit 0. Pod 1/1, 0 restarts at
t+70s; Keycloak 26.6.4 started in 9.1s with `jdbc-postgresql` loaded.
**Proof it used our database, not dev-file:** querying the CNPG instance directly returned
**90 tables**, realm `master`, 1 user — the bootstrap admin created from the Vault-seeded password.

**`KC_HOSTNAME` is phase-1-scoped and the port-forward port must match it.** Set to
`http://localhost:8080`. With `KC_HOSTNAME` on 8080 but the forward on 18080, the login form posts
to a different origin, the session cookie does not match, and the POST returns 400. Change both
together or neither.

**Step 5 — PASS, exit 0.** Conformance realm + confidential client + user (neutral, deliberately
not ok2-rmf). Authorization-code + **PKCE** completed via browser-style form login; code exchanged
with the verifier; **RS256 signature VERIFIED against the advertised JWKS** (PyJWT, matching `kid`),
id_token verified, refresh token present; client-credentials grant issued; wrong client secret
denied 401. State survived deleting **both** the Keycloak and the PostgreSQL pod.

Three traps, all real:
- **`UID` is a readonly bash variable** — assigning it silently fails and a lookup goes to uid 1000.
- Keycloak 26 enforces `VERIFY_PROFILE`: a user without email/first/last name is redirected to a
  required-action page instead of completing the flow. Give the test user a full profile rather
  than disabling the check.
- A stray `kubectl port-forward` from an earlier step still held 8080 and silently served the wrong
  origin. Kill forwards by PID between steps; deleting a pod also kills its forward, which will
  make a survival check report false zeros if not re-established.

**Step 6 — post-check.**
- *Unchanged, as required:* `sys/health` 200 with every baseline field identical; served
  certificate still `CN=vault.ok-shared.internal` issued by `CN=ok-shared-internal-ca`, verify code
  0 (Vault's own cert, so the passthrough route is intact); all three peers unsealed, `ha=true`,
  indices advancing together (84265).
- *Changed, deliberately:* exactly six new managed resources, all `True/True` — `kubernetes/ok-shared`
  Backend, its AuthBackendConfig, roles `sa-keycloak` and `keycloak-seed`, policies
  `okvc-ok-shared-sa-keycloak` (read) and `okvc-ok-shared-keycloak-seed` (create/update) — plus two
  KV entries under `secret/data/ok-shared/keycloak/`.
- *Nothing else moved:* all pre-existing managed resources retain their original ages (2d21h, 4d21h,
  5d13h, 44h), so none was recreated or re-reconciled, and every rendered policy body is still
  scoped to its own cluster's subtree.
- *Functionally proven, not just inventoried:* `ok-obs-verify` and `ok-robotics` both still report
  `SecretSynced=True` at their current generation.

**What step 6 does NOT prove.** A complete Vault configuration diff needs an admin token to list
`sys/policies` and `sys/auth`; we deliberately hold no such token. The assertions above are at the
reconciler level (what Crossplane manages, with ages) plus a functional test of the other
consumers. A hidden change made directly in Vault by another party would not be caught by this.

---

# Cycle defects — what a real `teardown` + `install` exposed

The Makefile was transcribed from the manual run above and looked correct: it read cleanly, its
guards fired when broken, and `make -n` showed the right sequence. **Every defect below survived
that review and was only found by destroying the deployment and rebuilding it.** Two full cycles
now pass; these are what it took.

### 1. `kubectl wait --for=jsonpath='{.data.token}'` is not a valid form
`error: jsonpath wait format must be --for=jsonpath='{.status.readyReplicas}'=3`. This kubectl
(client v1.27.4) requires `--for=jsonpath=<expr>=<value>`; waiting on mere *presence* of a field is
not expressible. Replaced with a bounded poll for a non-empty token, which is what actually matters
— the token controller populating the Secret.

### 2. Teardown deleted an identity that the retained Vault config depends on  ← the important one
`teardown-identities` removed the reviewer ServiceAccount, its ClusterRoleBinding and its token
Secret. But teardown deliberately **retains** the Vault-side configuration, and that configuration
authenticates TokenReview using *that ServiceAccount's JWT*, copied to ok-mgmt. After a rebuild the
SA is new, the stored JWT belongs to a deleted one, and **every Vault login returns 403** — the
seeder's and VSO's alike. Diagnosis: reviewer SA created `12:47`, stored JWT created `10:29`.

Two consequences worth carrying:
- **The reviewer identity is part of the Vault-side surface, not the app.** It is now retained by
  `teardown-identities`, with an opt-in `teardown-reviewer` that states plainly what it breaks.
- **A Vault field the provider cannot read will never self-heal.** `token_reviewer_jwt` is
  write-only, so provider-vault sees no drift and never re-pushes it. Refreshing the Secret on
  ok-mgmt was not enough; the `AuthBackendConfig` managed resource had to be deleted so the
  composition recreated it and re-read the Secret. It reported `Synced=True` throughout — a
  Synced managed resource is not evidence that the value in Vault is current.

### 3. `seed` was not re-runnable, by construction
`cas=0` means create-only, and teardown deliberately leaves KV intact — so the second `install`
always failed with `check-and-set parameter did not match the current version`. The seeder cannot
read, so it cannot check first. Resolution: treat **that exact error** as "already seeded, existing
value kept"; any other non-200 still fails. A consequence worth knowing: the generated password is
then discarded and **the Vault value survives a rebuild**, which is why the admin credential keeps
working after the database is destroyed.

### 4. `kubectl wait --timeout=1s` used as an "assert now" idiom is a race
`post-check` failed with `timed out waiting for the condition on clusters/keycloak-db` while the
cluster was reporting `Ready=True`. `wait` must establish a watch inside that second against a
remote API. Assertions about current state are now direct reads of the condition, which cannot race.

### 5. The VSO pre-activation guard blocked re-runs
The guard refuses to install VSO while any VSO custom resource exists — correct, because starting
the operator reconciles everything at once. But on a re-run the CRs present are the ones this
capability created, and the operator is already running, so there is nothing to activate. Now
skipped when the controller Deployment exists, with the reasoning in a comment.

### 6. `VAULT_LB` hardcoded an environment IP
`192.168.100.207` is specific to this installation, and it is **not discoverable from ok-shared** —
the LoadBalancer lives on ok-infra, and ok-shared's own Traefik Service reports `EXTERNAL-IP
<pending>`. Auto-discovery would mean requiring a second kubeconfig to seed a secret.

- `seed` never needed it: it now port-forwards to `svc/vault-active` and addresses
  `https://vault-active.$(VAULT_NS).svc.cluster.local:<local-port>` with `--resolve`. TLS still
  verifies because the certificate's SAN already covers that name. No IP, no DNS, no LoadBalancer.
- `baseline` genuinely needs an external address, because probing the consumer route *is* the
  check. `VAULT_LB`/`VAULT_HOST` now default to **empty**: the target verifies Vault over a
  port-forward and prints that the external passthrough route was **not** exercised. Supplying the
  address restores the external probe. A silent fallback would let a run claim it verified the
  passthrough route when it had not.

### Known flake, not fixed
One `baseline` run exited non-zero on what appears to be a port-forward readiness race; five
subsequent runs passed unchanged. It has been seen once and is not understood, so treat it as a
known flake and add a retry before running this unattended.

### What two clean cycles proved
`teardown` exit 0 → `install` exit 0, twice, with no intervention and no external address supplied.
Each rebuild issued a **new realm signing key** (`kid` changed every cycle), so the pass reflects a
genuine rebuild rather than surviving state. Afterwards: both pods `1/1` with zero restarts, no
leaked port-forwards, Vault healthy, and `ok-obs-verify` / `ok-robotics` XRs still `True/True`.

---

## Targets `admin-cutover` (step 5.7) + `rotation-test` (step 5.8) — added 2026-08-03

Driven by the console banner *"You are logged in as a temporary admin user…"*. Both targets are
gated on `APPROVE_CUTOVER=yes` and refuse to run unattended.

**What the banner actually is.** Read live before designing anything: `master` held exactly one
user, `admin`, with attribute `is_temporary_admin: ["true"]`. The banner follows that attribute, so
only deleting the account clears it honestly. Flipping the attribute was considered and rejected —
it silences the notice while leaving the bootstrap account and its provenance in place.

**`admin-cutover` — PASS.** Rename `admin` → `bootstrap-admin` (needs `editUsernameAllowed` on
`master`, restored to `false` and re-read afterwards), create permanent `admin` + realm role
`admin`, verify it authenticates / can list realms / carries no temporary flag, **escrow to
`secret/data/ok-shared/keycloak/admin` (version 2) and log in with the materialised Secret**, then
delete `bootstrap-admin` using the new admin's own token. End state asserted: `master` users ==
`['admin']`, no account carries `is_temporary_admin`, old bootstrap password refused.

**`rotation-test` — PASS.** Admin: rotate via Keycloak API → new works, old refused; the
Vault-materialised Secret still holds the old value and **no longer authenticates**; a value written
to **Vault alone** (version 5) does **not** authenticate while Keycloak keeps accepting only what its
own API set; then converge (version 6). Database: write `…/keycloak/db` (version 2) → Secret updates
→ CNPG `passwordStatus.keycloak.resourceVersion` advanced `1734749 → 2583952` → `psql` accepts the
new value, refuses the old one with `password authentication failed` → Keycloak pod recreated →
StatefulSet Ready, discovery served, admin login works. `make verify` re-run afterwards: STEP 5 PASS
with a fresh realm signing key.

## Cycle defects — round two (found by running the above)

### 7. Escrowing the new credential LAST destroyed it  ← the important one
The first cutover put the Vault write after the end-state assertions. A wrong assertion (see 8)
aborted the run, and the freshly generated permanent-admin password existed nowhere but a
`mktemp -d` work dir that the script's own `trap … rm -rf` then deleted. The cutover itself had
succeeded — `master` was left with a single non-temporary `admin` whose password nobody held, and
the console was locked out. Fixed two ways: **escrow now happens before anything destructive**, and
**work dirs are retained** (mode 700) with their path printed, never auto-deleted.

### 8. Asserting `401` for a rejected password grant
Keycloak answers a bad password grant with **`400` + `error=invalid_grant`**; `401` is for *client*
authentication failure. The assertion failed a cutover that had actually worked. Now asserts
not-200 **and** `invalid_grant`.

### 9. `kc.sh bootstrap-admin user` cannot use the pod's ports
Break-glass recovery inside the running pod dies with `Unable to start the management interface on
0.0.0.0:9000 — Address already in use`, because the command boots a partial server alongside the
live one. `recover-admin` overrides `KC_HTTP_PORT` / `KC_HTTP_MANAGEMENT_PORT` for that invocation.

### 10. `SecretSynced=True` is not a rotation gate
After a Vault write the `VaultStaticSecret` generation is unchanged, so `wait-vso-current.sh` passes
instantly and proves nothing about the new value. Rotation uses `wait-secret-value.sh`, which
compares the destination Secret's value against the expected one (by comparison, never printing).

### 11. A `psql` negative that cannot tell "refused" from "unreachable"
An unreachable server and a rejected password both fail. The database negative now requires the
error to contain `password authentication failed`. The CNPG container filesystem is read-only, so
psql's stderr is captured into a variable rather than spooled to a file in the pod.

### 12. `verify`'s port-bind precheck trips on TIME-WAIT
Sockets left in `TIME-WAIT` on `127.0.0.1:8080` from a previous run make the plain `bind()` check
report `Address already in use`, so `verify` refuses to start for ~60s after another target used the
port. Not fixed — waiting clears it, and the check is doing its job otherwise.

### Not done
`extraEnv` still carries `KC_BOOTSTRAP_ADMIN_*`, and `require-values-contract` asserts they are
present. Retiring that wiring (so an empty database cannot recreate a temporary admin) is a values
change plus a Helm upgrade plus a contract change — a reviewed change of its own.

---

## OK-81 hardening implementation — local evidence boundary (2026-08-03)

Backup/restore-drill, bootstrap-wiring retirement, brute-force protection, and portable Kubernetes
NetworkPolicy targets were implemented after the permanent-admin cutover. This delegated write
session was explicitly prohibited from touching a live cluster, so it did **not** run the Helm
upgrade or the `backup`, `restore-drill`, `brute-force`, `verify`, rotation, CNPG-readiness, or
NetworkPolicy apply checks on ok-shared. Local syntax, render, Helm-template, guard-failure, and
dry-run evidence is recorded in the implementation report; live results must be appended only by
the coordinator that actually runs them. No claim in this section is live-cluster evidence.

## Hardening — LIVE results on ok-shared, run by the coordinator (2026-08-03)

Fills the gap the section above declares. Everything below was executed against ok-shared and is
what the commands returned. Final state: both pods `1/1` with 0 restarts, three NetworkPolicies
applied, `make verify` PASS.

| Target | Result |
|---|---|
| `backup` | PASS — 225066-byte `pg_dump -Fc` artifact, mode 600, validated by `pg_restore --list` |
| `restore-drill` | PASS — scratch db `kc_restore_20260803052201_18387_13171`; restored `realm=2 client=14 master=1`; dropped and re-queried, zero `kc_restore_%` databases left |
| values change + `keycloak` | PASS — `helm template` greps zero `KC_BOOTSTRAP_ADMIN`, `KC_DB_PASSWORD` still a `secretKeyRef`; rollout to revision `keycloak-keycloakx-8887684b7` complete |
| `brute-force` | PASS — and confirmed independently in PostgreSQL, not just by the script's own re-read: `realm_attribute` holds `bruteForceProtected=true`, `failureFactor=5`, `permanentLockout=false`, `maxFailureWaitSeconds=900` |
| `network-policy` | Applied after the fixes below. Cross-namespace probe went `OPEN → BLOCKED` on 9000 and 5432 against a baseline captured *before* any policy existed; `make verify` PASS under the policy; CNPG `Ready=True` |
| `rotation-test` | Part A PASS end to end after the lockout fix (admin KV versions 9 → 10). Part B completed manually after the CNPG defect below: `psql` accepts the rotated credential, Keycloak restarted and came back Ready on it |

**Baseline that made the NetworkPolicy provable.** Before applying anything, a busybox pod in
`default` reached `keycloak-keycloakx-http:80`, `:9000` and `keycloak-db-rw:5432` — all OPEN, with
`kubectl get netpol -A` returning nothing. Without that recorded before-state a policy selecting zero
pods would have passed every liveness check. Capture it first or the negative half is unprovable.

## Cycle defects — round three (found only by running it live)

### 13. `ipBlock` cannot express API-server egress on Cilium  ← the important one
The policy allowed the CNPG instance egress to `0.0.0.0/0:443` as a "portable compromise" for
reaching the Kubernetes API. It does not work: Cilium does not match CIDR selectors against
cluster-internal identities such as `kube-apiserver`. Applied, the instance manager logged
`apiServerReachable:false` / `Get "https://10.96.48.1:443/apis/postgresql.cnpg.io/..." context
deadline exceeded`, fell back to a **cached cluster definition**, and stopped reconciling the managed
role — so a genuinely rotated database password never reached PostgreSQL while the Cluster still
reported `Ready=True`. `pwRV` stayed at `2601243` against a Secret at `2604138` for over five
minutes, then advanced within seconds of removing the egress restriction. Adding port 6443 was not
the fix and was a red herring: the traffic goes to the ClusterIP on 443.
**Fixed** by making `keycloak-db` and `default-deny` **ingress-only**. Ingress is where the exposure
actually was; expressing that egress would need a `CiliumNetworkPolicy` with
`toEntities: [kube-apiserver]`, trading portability for a rule of little value.

### 14. Brute-force protection makes `rotation-test` lock itself out
`rotation-test` performs deliberate failed logins as `admin`. With `failureFactor=5` now enabled it
tripped the lockout mid-run, the next *correct* login failed for an unrelated reason, and the script
died between "write a throwaway value to Vault" and "converge" — leaving Vault holding the throwaway
while Keycloak held the real password, i.e. the escrow silently wrong. Recovery used the retained
work dir, which is the second time that retention rule has prevented a lost credential.
**Fixed**: `clear_lockout` calls the attack-detection endpoint after each negative assertion, while
the counter is still below the threshold and a token can still be obtained.

### 15. `verify` was only re-runnable against a fresh database
`keycloak-conformance-test.sh` tolerated `409` on test-user creation, then authenticated with the
password it had just generated and never applied — so step 5 failed on any second run. This is
pre-existing, and it mattered because it made an unrelated values change look guilty.
**Fixed**: on 409, reset the existing user's password to this run's value.

---

## Bootstrap/install + NetworkPolicy rerun fix — LIVE on ok-shared (2026-08-03)

This follow-up fixes two defects exposed by the live hardening cycle above. It does not retract the
incident notes: they are the reason the new checks exist.

### Decisions

- `install` requires `APPROVE_CUTOVER=yes` and an attended terminal before its first step, and passes
  that approval to the idempotent `admin-cutover`. A fresh install must not silently rewrite admin
  identity, but it also must not stop routinely with no usable account. Requiring approval at entry
  makes the mutation explicit without leaving an operator to discover a half-finished install.
- `admin-cutover` runs immediately after Keycloak becomes Ready; `verify` runs after cutover and
  therefore reads the re-escrowed permanent credential. Running `verify` only before cutover would
  prove the temporary credential while leaving the final identity and escrow result untested.
- `network-policy` now proves the allowed path with `make verify`, the denied path from a disposable
  pod in `default` (`9000` and `5432` must both be `BLOCKED`), CNPG `Ready=True`, and the absence of
  recent `apiServerReachable:false` instance logs. The Secret-delete/rematerialise/resourceVersion
  sequence was removed rather than shortened: CNPG is not required to re-apply an unchanged
  password, so waiting for its status resourceVersion to advance was not evidence of policy health.
- Rollback remains only around the apply plus direct behaviour proofs. It restores each policy that
  existed at entry in place, and deletes only a same-named policy introduced by that run. There is
  no rollback driven by a slow reconciliation wait, and a rerun cannot leave fewer policies than it
  started with.

### Values + live Helm upgrade

`KC_BOOTSTRAP_ADMIN_USERNAME` and `KC_BOOTSTRAP_ADMIN_PASSWORD` again read `username`/`password`
from Secret `keycloak-admin`. They seed only an empty database; the live database already held the
permanent account, so the Helm upgrade changed no identity state.

```text
$ make require-values-contract
require-values-contract: PASS

$ helm template ... | grep -n KC_BOOTSTRAP_ADMIN
175:            - name: KC_BOOTSTRAP_ADMIN_USERNAME
180:            - name: KC_BOOTSTRAP_ADMIN_PASSWORD

$ helm upgrade --install keycloak ... -f values-ok-shared.yaml
Release "keycloak" has been upgraded. Happy Helming!
STATUS: deployed
REVISION: 3

$ kubectl rollout status statefulset/keycloak-keycloakx -n keycloak --timeout=5m
statefulset rolling update complete 1 pods at revision keycloak-keycloakx-79dcd9467c...

$ make verify ...
STEP 5: PASS
```

The values contract was first run against a deliberately mutated input with the bootstrap password
entry removed. It failed closed with:

```text
ERROR: VALUES_FILE does not match CNPG/VSO/admin-bootstrap/database/port variables
make: *** [Makefile:168: require-values-contract] Error 2
```

### Gates observed refusing

```text
$ make install ...                         # no APPROVE_CUTOVER
ERROR: this target mutates live admin/database credentials on cluster ok-shared.
       Review the sequence, then rerun with APPROVE_CUTOVER=yes.

$ make network-policy ...                  # no APPROVE_NETWORK_POLICY
ERROR: network-policy changes live traffic isolation on cluster ok-shared.
       Review the rendered policy and rollback path, then rerun with APPROVE_NETWORK_POLICY=yes.
```

With the respective approval variable present but stdin unattended, the same gates returned
`credential cutover/rotation must be run attended from a terminal` and
`network-policy must be run attended from a terminal`.

### Regression: `network-policy` twice against the existing policies

Both attended invocations used `APPROVE_NETWORK_POLICY=yes` and returned the same proof:

```text
networkpolicy.networking.k8s.io/keycloak configured
networkpolicy.networking.k8s.io/keycloak-db unchanged
networkpolicy.networking.k8s.io/default-deny unchanged
STEP 5: PASS
keycloak-keycloakx-http:9000 BLOCKED
keycloak-db-rw:5432 BLOCKED
RESULT: PASS — allowed Keycloak traffic is healthy; external ports 9000/5432 are BLOCKED;
CNPG is Ready=True with API reachability intact
```

The negative predicate was also made to fail deliberately against the reachable Kubernetes API
before it was trusted: `kubernetes:443 OPEN` made the assertion exit non-zero. The same disposable
probe then returned `BLOCKED` for both protected ports. No probe pod remained afterwards.

### Final state

```text
$ kubectl get networkpolicy -n keycloak default-deny keycloak keycloak-db
NAME           POD-SELECTOR
default-deny   <none>
keycloak       app.kubernetes.io/instance=keycloak,app.kubernetes.io/name=keycloakx
keycloak-db    cnpg.io/cluster=keycloak-db

$ kubectl get cluster.postgresql.cnpg.io keycloak-db -n keycloak ...
NAME          READY
keycloak-db   True

$ kubectl get pods -n keycloak ...
NAME                   READY   RESTARTS
keycloak-db-1          true    0
keycloak-keycloakx-0   true    0

$ psql ... # direct read of every user in master plus the temporary attribute
admin|is_temporary_admin=<absent>

$ kubectl logs keycloak-db-1 --all-containers --since=10m | check apiServerReachable:false
none

$ kubectl get statefulset keycloak-keycloakx ... # live env name, Secret name, Secret key
KC_BOOTSTRAP_ADMIN_USERNAME  keycloak-admin  username
KC_BOOTSTRAP_ADMIN_PASSWORD  keycloak-admin  password
```

The empty-database path was deliberately not executed because doing so would destroy the only live
realm data. Its exact path is now: VSO materialises the seeded `keycloak-admin` Secret; Helm injects
that Secret through `KC_BOOTSTRAP_ADMIN_*`; Keycloak creates the temporary first `admin` only because
the realm is empty; attended `admin-cutover` replaces it with the permanent `admin` and updates the
same Vault KV path; then `verify` authenticates with that newly materialised permanent credential.
No break-glass target or recovery KV path participates.

## Full teardown + install acceptance cycle (2026-08-03) — PASS

The gate that incremental verification cannot substitute for. A fresh backup was taken first
(226320 bytes), then `make teardown CONFIRM=yes`, then `make install … APPROVE_CUTOVER=yes`.

**`install` exit 0 from an empty database, with no break-glass step.** Sequence run:
`baseline install-vso identities seed vso-wiring database keycloak admin-cutover verify post-check`.
The fresh-database admin path — which the delegated session could not test without destroying live
data — is now proven: Keycloak minted the temporary `admin` from the Vault-escrowed credential that
`seed` preserves (KV is retained by teardown, `cas=0` keeps it), `admin-cutover` renamed it to
`bootstrap-admin`, created the permanent `admin`, escrowed to `…/keycloak/admin`, deleted the
temporary account, and asserted `master` users == `['admin']` with no `is_temporary_admin`. The old
bootstrap password was then refused. `verify` PASS with a **new** realm signing key
(`kid=RDXkPl-E8rxF…`) and a new `sub`, so the pass reflects a genuine rebuild rather than surviving
state.

**State reproduced exactly.** Pre-teardown vs post-cycle: `master` 1 user / `ok-conformance` 2 users,
`bruteForceProtected=true` + `failureFactor=5`, 3 NetworkPolicies, both pods Ready with 0 restarts,
CNPG `Ready=True`.

**`install` does not include the hardening steps, by design** — `brute-force` and `network-policy` were
re-applied afterwards and both returned PASS, the latter with `9000` and `5432` BLOCKED from outside the
namespace. Anyone rebuilding must run those two, or the rebuild is unhardened. Worth folding into a
documented post-install phase.

**One transient failure, worth recording rather than hiding.** The first `install` attempt died at
`baseline` with no diagnostic: two `jq -e` assertions there fail silently. Re-run standalone,
`baseline` passed (exit 0, raft peers `[204123,204123,204123]`), and every assertion was verified by
hand — Vault health `200` with `initialized/sealed/standby` correct, all three peers unsealed with
`ha_enabled` and matching raft indices. It was the port-forward race right after teardown deleted
namespaces, i.e. the flake already recorded above. **Defect:** those assertions should print what they
saw; a silent `jq -e` inside a `set -e` recipe is indistinguishable from a real regression.

## `ClusterIssuer` for `.internal` names (2026-08-03)

Certificate blocker for ingress/OIDC resolved by **reusing** the ADR-025 CA rather than minting a
second trust root. `platform/networking/cert-manager/cluster-issuer-internal-ca.yaml` adds
`ClusterIssuer/ok-shared-internal-ca` backed by a copy of the existing CA secret in cert-manager's
cluster-resource namespace (`--cluster-resource-namespace=$(POD_NAMESPACE)`, verified).
`Ready=True — Signing CA verified`, and a probe `Certificate` for `keycloak.ok-shared.internal`
requested from the **`keycloak`** namespace was issued and chains to `CN=ok-shared-internal-ca`;
the probe was deleted. Accepted cost: the CA private key now exists in two namespaces. Rejected
alternatives (a `selfSigned` ClusterIssuer, `--cluster-resource-namespace=vault`, trust-manager,
Vault PKI) are argued in that file's header. DNS for `.internal` still blocks ingress independently.

## Post-install hardening is now a make phase, and `baseline` no longer fails silently (2026-08-03)

**`harden` phase.** The teardown/install cycle exposed that a rebuild comes back *unhardened*: the
brute-force policy lives in `master`'s realm attributes and the NetworkPolicies live in the namespace,
so neither survives a teardown, and `install` did not restore them. `harden` now runs `brute-force`
then `network-policy` — that order because the realm setting is trivially reversible while the policy
changes live traffic isolation and carries the heaviest proof — and `install` calls it between `verify`
and `post-check`, so `post-check` validates the final hardened state rather than an intermediate one.

`harden` is gated on `require-network-policy-approval` **as a prerequisite**, not per-sub-target. The
first version gated only `network-policy`, so a run without approval applied brute-force and *then*
refused — a partially applied phase. It now refuses before touching anything (verified: no
`RESULT: PASS` from brute-force appears). `make install` therefore needs `APPROVE_CUTOVER=yes` **and**
`APPROVE_NETWORK_POLICY=yes`; the help text says so, because discovering it at the last step of a long
install is the worst place to learn it.
*Verified:* refuses without approval; runs clean with it; idempotent against an already-hardened
cluster (3 policies before and after, `9000`/`5432` still BLOCKED).

**`baseline` diagnostics.** Both `jq -e` assertions exited silently inside a `set -e` recipe, which is
why a transient failure was indistinguishable from a Vault regression and cost a false alarm. Both now
print what they observed before exiting. The health assertion additionally names the likely cause,
because the probable trigger was `standby=true`: the port-forward reaches `vault-active`, which can
briefly select a Raft standby while the cluster churns after a teardown.
*Proven to fire* by feeding the assertion a crafted `standby=true` document and confirming it reports
`initialized=true sealed=false standby=true …` plus the standby note, instead of exiting mute.

## Reachability blockers for ingress — measured, not assumed (2026-08-03)

| Prerequisite | State |
|---|---|
| Certificate for `.internal` names | **Solved.** `ClusterIssuer/ok-shared-internal-ca` Ready; cross-namespace issuance proven |
| Ingress controller | Present — `IngressClass/ok-ingress` (Traefik) |
| External address | **Not a blocker — corrected.** `svc/traefik` on ok-shared showing `extIP=<pending>` is EXPECTED: ok-shared does not run its own MetalLB by design. Reachability is **192.168.100.207:443** (the MetalLB IP on the **infra** cluster) → Traefik → **TLS passthrough** to the service |
| **Name resolution** | **The only remaining blocker.** Nothing under `.internal` resolves; ok-mgmt's CoreDNS has no `hosts`/`rewrite` entry, it only forwards to `/etc/resolv.conf`. Pinned to the IP above for now. The follow-up is **OK-57** — note its actual title is *"Multus NAD for CAPK VMs — vSwitch interface for Talos guest cluster nodes"*, i.e. it delivers node-level reachability rather than a DNS server; the repo already treats it as what makes `.internal` names resolvable/reachable (`platform/secrets/vault/crossplane/provider-vault.yaml`). For the API-server path specifically a CoreDNS `hosts` entry on ok-mgmt is enough and does not wait on OK-57 |

**Correction to an earlier reading in this file.** A previous version of this section called the
pending LoadBalancer IP a blocker and speculated that MetalLB's absence was drift from the ok-shared
onboarding profile. That was wrong, and it is worth recording why the mistake was easy to make: from
inside ok-shared a `LoadBalancer` stuck at `<pending>` looks exactly like a missing controller, and the
address that actually serves this cluster lives on a *different* cluster where nothing in this
repository points at it. `vault.ok-shared.internal` having an `IngressRouteTCP` with no local address
behind it is not a broken route — the address is upstream. `baseline` reporting the external SNI path
as "not exercised" when `VAULT_LB`/`VAULT_HOST` are unset is therefore about those variables being
unset, not about the route being absent.

**Consequence to settle before Keycloak ingress (open design question, not a defect).** The infra path
is TLS **passthrough**, which means the backend serves TLS itself — that is why Vault does. Keycloak
today serves plain HTTP (`KC_HTTP_ENABLED=true`, `proxy.mode=xforwarded`, `KC_HOSTNAME` on `http://`)
on the assumption that TLS terminates at the edge, and ADR-010 §"standard Ingress" reads as
termination rather than passthrough. Under passthrough Keycloak would instead need its own server
certificate — now trivially obtainable from `ClusterIssuer/ok-shared-internal-ca` — plus
`KC_HOSTNAME=https://…` and the chart's TLS wiring. Which of the two shapes applies to Keycloak is a
decision, and it changes `values-ok-shared.yaml`.

## Cycle defects — round four (found by testing TLS end to end, 2026-08-03)

TLS was exercised for real on ok-shared and then rolled back — phase 1 has no ingress. It worked
(chain verified against the internal CA, `http=200` over HTTPS with SNI `keycloak.ok-shared.internal`),
and it surfaced four traps that would each have cost a phase-2 debugging session.

### 16. Server TLS silently moves the management port to HTTPS, breaking the health probes
Setting `KC_HTTPS_CERTIFICATE_FILE` makes Keycloak log
`Management interface listening on https://0.0.0.0:9000`. The chart probes `http-internal` with
`scheme: HTTP`, so every probe fails with `EOF` and the pod never becomes Ready — while the server
itself is perfectly healthy. `http.internalScheme: HTTPS` fixes it. Nothing in the option's name
suggests it governs probes.

### 17. A StatefulSet wedges when its only pod cannot become Ready
`podManagementPolicy: OrderedReady` will not replace pod 0 until pod 0 is Ready, so a bad revision
cannot be rolled forward *or* back: `helm upgrade --wait` times out every time, indefinitely. The pod
must be deleted by hand to adopt the corrected template. Three consecutive failed Helm revisions came
from this single cause.

### 18. Deleting a mounted Secret before the workload stops referencing it
Rolling TLS back, the Certificate and its Secret were deleted in the same step as the Helm downgrade.
The still-running pod mounted that Secret, so it could not start, which wedged the StatefulSet per
defect 17. Order matters: change the workload first, remove the material afterwards.

### 19. Helm cannot remove env vars when `last-applied-configuration` is absent  ← the important one
After the failed revisions, `helm upgrade` reported `STATUS: deployed` and
`helm get values` showed no `KC_HTTPS_*`, yet the live StatefulSet still carried both. `kubectl apply`
of Helm's own stored manifest did not remove them either, warning that
`kubectl.kubernetes.io/last-applied-configuration` was **missing**: `env` is a merge-key list, so
without that annotation the three-way merge has no basis for computing deletions and preserves the
stale entries. Desired state was provably clean (`helm template … | grep -c KC_HTTPS` → 0) while the
cluster disagreed — the most dangerous shape of drift, because every artifact you would normally trust
says you are fine.
**Recovery that worked, and the right instinct:** `helm uninstall` + reinstall. It is safe here because
the release owns nothing stateful — the CNPG `Cluster`, its PVC, the VSO-materialised Secrets, the
NetworkPolicies and all realm data survived, verified afterwards (`master users=1`,
`ok-conformance users=2`, `bruteForceProtected=true`, 3 policies, `make verify` PASS,
`make diff` exit 0).

## Pending outward actions (not yet performed — deliberately)

- **OK-57 comment:** fold **CA distribution** into its scope. `ClusterIssuer/ok-shared-internal-ca`
  solves machine trust (`--oidc-ca-file` for the API server), but human console users get browser
  warnings until the CA is distributed to workstations. Alternative worth naming in the same comment:
  a cert-manager **Vault PKI** issuer, which copies no private key at all.
- Commits, PRs and every Jira update remain with the human reviewer.
