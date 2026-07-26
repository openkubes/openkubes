# ADR-Platform-025 — Amendment proposal (2026-07-26)

**Transient review artifact.** Commit-ready amendment text to fold into
**ADR-Platform-025** before it moves Draft → Accepted. Applied by a human after the
three-way review, then this file is removed (AI may argue; only humans merge). The
15-point acceptance-evidence matrix lives in the **OK-110 review thread** (Jira), not
here — to avoid a second normative truth next to the ADR.

**Governance note (Claude concedes to GPT).** A criterion listed under ADR-025's own
"Path to acceptance" remains an ADR-025 acceptance blocker even when another ticket
(OK-109 Part 1) executes it or another ADR (ADR-018) is its subject-matter home.
Delegating *execution* does not downgrade *acceptance status*; only an explicit ADR-025
amendment can. Fresh-install (crit. 7) and Vault-outage (crit. 8) are therefore treated
as **open blockers** unless A8 / A9 below are adopted by decision.

---

## A1 — Custody: Accepted Risk AR-025-1 (§Seal/unseal, §Artifact placement)

> **Phase-1 custody — Accepted Risk AR-025-1.** Vault uses five Shamir shares, threshold
> three. The shares are GPG-encrypted but are currently held under **single-operator
> custody** — recoverability without organisational **separation of duties**; OpenKubes
> explicitly accepts that concentration risk for Phase 1.
>
> **Hard gate — before multi-operator or external-production use.** Before use beyond the
> current single-operator environment (a second operator / on-call model, or external
> production workloads), Vault MUST be rekeyed to **distinct custodian PGP keys**, with
> share distribution + recovery rehearsed and evidence retained.
>
> **Root token — revoked (realised ceremony evidence, 2026-07-25).** The initial root
> token was used only to enable audit, admin auth and the automation seed, then revoked
> (`vault token revoke -self`, success recorded). **No standing root token exists.**
> Administrative break-glass is **`userpass/breakglass`** (a strong password under the same
> Phase-1 custody), and recovery uses the Shamir unseal ceremony — not a stored root token.

Replace every "**production gate**" phrasing with "**gate before multi-operator or
external-production use**" (avoids contradicting "Vault is already operational").

## A2 — Reachability: Path A becomes the accepted wording (§Cross-cluster reachability)

The current text assumes a child-cluster / "ok-shared ingress **MetalLB IP**" and a
consumer-side CoreDNS entry to that child IP. Reality: **child clusters run no MetalLB.**

> **Current reachability profile — Path A (host-level LoadBalancer).** Consumers resolve
> `vault.ok-shared.internal` to the stable **host-cluster** LoadBalancer address
> `192.168.100.207`, allocated by **MetalLB running on `ok-infra` (the host cluster), not in
> the child cluster** (the `ok-mgmt-lb` pattern). The host LoadBalancer forwards TCP/443 to
> the ok-shared Traefik entrypoint (NodePort 30443); Traefik routes by
> `HostSNI(vault.ok-shared.internal)` with **TLS passthrough** to the leader-only
> `vault-active` Service. TLS is **end-to-end**; the host layer does not terminate or inspect
> Vault traffic.
>
> **Path B (optional).** Native child-cluster LoadBalancer reachability via Multus/NAD (so
> `vault.ok-shared.internal` resolves to a **child-owned** LB IP) is an optional simplification
> tracked by **OK-57**, **not** an ADR-025 acceptance prerequisite.

Consumer-side obligation changes: resolve `vault.ok-shared.internal` to the **host-cluster LB
IP `192.168.100.207`**, not a child MetalLB IP; SNI + CA trust unchanged. Implementation:
`hostAliases` pin to `.207` (provider-vault on ok-mgmt); VSO `address:
https://192.168.100.207:443` + `tlsServerName`. Part of the ADR-025 profile — no separate ADR.

## A3 — Acceptance criterion 15 → Path A

> 15. **Non-manual cross-cluster reachability** proven via **Path A**: consumer reaches Vault
> over the stable host-cluster LoadBalancer (`192.168.100.207:443`, MetalLB on **ok-infra**) →
> ok-shared Traefik `IngressRouteTCP` (TLS passthrough, `HostSNI(vault.ok-shared.internal)`,
> `vault-active` backend), cert-manager server TLS, consumer-side CA trust — replacing the PoC's
> manual host-cluster LB proxy. Path B (native child LB, OK-57) is optional, not a gate.

## A4 — Acceptance criterion 3 → per-instantiated-category evidence

> 3. **Authentication topology applied per cluster.** For each onboarded cluster, evidence is
> required only for its **selected** authentication category. Categories not currently
> instantiated remain **activation-gated profiles, not acceptance dependencies** (Category A
> proven on ok-robotics; B and C gated until such a cluster exists).

## A5 — ADR-011 consistency + ADR-020 non-acceptance (§Decision)

> **Backend:** Vault on ok-shared, **selected by this datacenter implementation profile under
> the Secret Contract** (ADR-011 permits Vault as a per-envelope profile; it does **not** require
> Vault). ADR-025 accepts **one bounded shared singleton** for the datacenter Secret profile. It
> does **not** establish a Shared Platform Services Contract, a `TYPE=shared` lifecycle, an
> `ok-shared` capability repository, or acceptance of **ADR-020** (which stays Draft).

## A6 — Revision identity + automation policy (make reconciler realities normative)

> **Revision identity (extends line 149).** `provider-vault` pinned to **v4.0.1**; the managed-
> resource APIs used are **`v1alpha1`** (cluster-scoped `*.vault.upbound.io`; namespaced
> `*.m.upbound.io` variants unused). API maturity is an **explicit revision characteristic**, not
> an assumed stability guarantee.
>
> **`ok-config-automation` least-privilege policy — exact grants (versioned).**
> `sys/auth`(read), `sys/auth/*`(create,read,update,delete,sudo), `sys/mounts/auth/*`(read),
> `sys/policies/acl/*`(CRUDL), `auth/kubernetes/*`(CRUDL), **`auth/token/create`(create,update)**.
> Rationale: `sys/mounts/auth/*` read — the provider **observes** an auth backend via
> `sys/mounts/auth/<path>`; `auth/token/create` — the Upjet terraform-provider-vault mints a
> limited **child token per operation** (without it every MR gets 403). **Required negative test
> (blocks the least-privilege claim / crit. 13):** prove the automation identity **cannot** manage
> foreign mounts or higher-privileged policies.

## A7 — Realised acceptance evidence (reference block for ADR-025 visibility)

Add a concise "Acceptance evidence — realised (2026-07-26)" block so the proven items are
referenced *in* ADR-025 (GPT: proven-externally must be visible, not merely asserted):

> - **Bootstrap ceremony:** init 5/3 Shamir; audit device enabled; **root token revoked**;
>   break-glass `userpass/breakglass`. Cold-restart rehearsal: **89s**, `voters=3/3`, threshold met.
> - **Category-A reviewer model:** dedicated SA `vault-reviewer` + `system:auth-delegator`;
>   Vault mount `auth/kubernetes/<cluster>` configured with `token_reviewer_jwt` (not just a
>   successful TokenReview).
> - **Migration without credential change:** existing `ok-observability-credentials` taken over by
>   VSO (`overwrite`), **identical values, zero workload restarts**, OK-79 contract gate green.
> - **Rotation (rotatable credential):** `secret/ok-robotics/obs/rotation-demo` key `token`,
>   **`v1-alpha → v2-bravo`** → VSO refresh → `rolloutRestartTargets` → consumer read new value.
>   (Explicitly **not** the OpenSearch bootstrap password.)
> - **Reachability:** Path A, MetalLB on **ok-infra** (A2).
> - **Backup/restore:** **manual** external Raft snapshot + **restore rehearsal** (rollback
>   proven). Record the snapshot **location, SHA-256, restore-run outcome, and retention/deletion**
>   to fully satisfy crit. 11. **Scheduled off-host backup (CronJob / object store) remains a Day-2
>   follow-up — do not claim automated backups exist.**

## A8 — DECISION REQUIRED (Arash): criterion 7 (fresh install)

Two governance-valid options — pick one; do not leave as silent "delegated":
- **(i) Keep as blocker.** Criterion 7 stays open; evidence referenced later from **OK-109 Part 1**
  (fresh-cluster full-workflow run, Suchit). ADR-025 not Accepted until then.
- **(ii) Amend to reschedule.** Reword criterion 7 to *"before declaring the full install workflow
  conformant"* (i.e. out of the immediate Category-A profile acceptance), with OK-109 Part 1 named
  as the owner. Requires this explicit amendment.

## A9 — DECISION REQUIRED (Arash): criterion 8 (Vault outage + reconciliation)

Subject-matter is **ADR-018** autonomy, but ADR-025 lists it (crit. 8) **and** in its normative
Autonomy section. Options:
- **(i) Keep as blocker** and produce the evidence (cut Vault → existing workloads + a pod restart
  survive → reconcile after Vault returns). Cheap to run; also closes ADR-018.
- **(ii) Amend** to move the evidence to ADR-018 and have ADR-025 *reference* it. Requires an
  explicit amendment to both the Autonomy section and criterion 8.

Recommendation (Claude): **A9(i)** — just run the outage test; it's cheap, closes both ADRs, and
avoids weakening the autonomy story by amendment.

---

## Still open after this patch (no amendment can waive without the work)

- **Crit. 13** — negative automation-policy test (least-privilege claim).
- **Crit. 14** — singleton-invariant **enforcement** (admission/conformance) — currently not
  enforced; honest open blocker while the ADR says "enforced".
- **Crit. 8** — outage test, unless A9(ii) is chosen.
- **Crit. 7** — fresh install, unless A8(ii) is chosen.

Custody and reachability are **no longer blockers** once A1/A2 are folded in. GPT's final vote:
not Accepted while 8, 13, 14 are open — unless 7/8 are moved by deliberate amendment.
