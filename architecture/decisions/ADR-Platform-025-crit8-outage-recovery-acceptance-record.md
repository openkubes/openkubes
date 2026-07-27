# ADR-Platform-025 — Criterion 8 Vault-Outage + Recovery Acceptance Record

**Scope:** ADR-Platform-025 acceptance **criterion 8** (and the ADR-018 autonomy outage
evidence) — prove Vault is a **soft runtime dependency**: during a full Vault outage the
materialised consumer Secret is still served and workloads (incl. a pod restart) survive; after
Vault returns and is re-unsealed, the reconciler/VSO recover and a rotation propagates.

**Status:** Runbook + evidence tooling committed; **live evidence PENDING** the scheduled outage
window on ok-shared/ok-robotics. Fill the placeholders, attach `crit8-evidence.log`, then flip
Status to *Verified*.

> ✅ **UNBLOCKED (2026-07-27).** OK-113 resolved: Vault was re-seeded with fresh, **decrypt-verified**
> Shamir custody — the same shares were used to live-unseal all three voters and to mint a root
> token (`generate-root`), and break-glass was reset and login-verified. Seal recovery is
> demonstrable again, so the scale-to-0 outage test is safe to run. crit. 8 execution can now be
> scheduled.

---

## Method (decided)

Full outage simulated by **scaling the ok-shared `vault` StatefulSet to 0** (deterministic,
reversible, no data loss — Raft PVCs persist; pods return sealed and rejoin). Recovery is an
**attended Shamir re-unseal** (Phase-1, AR-025-1). Procedure: `runbooks/vault-outage-recovery.md`.

Artifacts:

| Item | Path |
|---|---|
| Runbook | `platform/secrets/vault/runbooks/vault-outage-recovery.md` |
| Evidence snapshot (read-only) | `platform/secrets/vault/conformance/outage-evidence.sh` |
| Make target | `make -C platform/secrets/vault outage-evidence EV_ARGS="--phase <name> --out crit8-evidence.log"` |

## The invariant

The consumer Secret `ok-observability-credentials` (ns `ok-observability` on ok-robotics) is
**present at every phase**, with an **unchanged content hash** until the deliberate rotation in
Phase R. `outage-evidence.sh` exits non-zero if the Secret is ever absent while Vault is down.

## Live evidence (fill on the window)

Environment: Vault `ok-shared` ns `vault` StatefulSet `vault` (3/3, v1.20.1); consumer
`ok-robotics` ns `ok-observability`.

**Per-phase snapshots** (paste the `outage-evidence.sh` `secret=`/`hash=`/`vault_pods=`/`sealed=`
rows from `crit8-evidence.log`):

| Phase | Secret present | Content hash | Vault pods | Sealed | Notes |
|---|---|---|---|---|---|
| baseline | | `H0=________` | 3 | false | |
| after-pod-restart (Test A) | | should equal H0 | 3 | false | quorum held; vault-0 re-unsealed |
| outage-start (Test B1) | | should equal H0 | 0 | — | VSS reports source error (expected) |
| outage-after-consumer-restart (B2) | | should equal H0 | 0 | — | consumer pod Ready **while Vault down** |
| recovered | | should equal H0 | 3 | false | 3/3 re-unsealed, Raft quorum restored |
| reconciled (Phase R) | | `H1=________` (rotated) | 3 | false | rotation-demo propagates via VSO |

**Key observations to confirm:**
- [ ] Test A: single `vault-0` restart transparent to the consumer (Secret hash = H0).
- [ ] B1: at 0 Vault pods, Secret still PRESENT and = H0; workloads still Ready.
- [ ] B2: a consumer pod deleted **during** the outage returns Ready from the existing K8s Secret.
- [ ] Recovery: `make health-gate` shows RaftHealthy 3/3 after attended re-unseal.
- [ ] Phase R: `VaultStaticSecret SecretSynced=True` and the rotation-demo value updates downstream.

Attach: `crit8-evidence.log`.

## Sign-off

- Three-way review (Arash / Claude / GPT): `__________`
- Criterion 8 closed + ADR-018 autonomy outage evidence recorded on: `__________`

## Notes

- Blast radius: scaling Vault to 0 is a real outage for **all** datacenter consumers; today only
  ok-robotics consumes, so it is bounded — still run in a scheduled window with unseal shares in
  hand (see the runbook's safety section).
- Recovery is attended by design (Phase-1 Shamir, AR-025-1); unattended auto-unseal is the
  committed follow-up (Transit/HSM).
