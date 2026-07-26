# Vault A6 migration & operations tooling

Reproducibility + evidence tooling for the **ADR-025 A6 ownership migration** and the break-glass
rotation (see `architecture/decisions/ADR-Platform-025-A6-ownership-migration-acceptance-record.md`).

> **These scripts are tooling and worked-example evidence — NOT normative platform config.** They
> are heavily **ok-robotics-specific and hardcoded** (managed-resource names/UIDs, mount paths,
> policy names, the `192.168.100.207` host-LB, the `okvc-` identity). They are kept for
> reproducibility, audit, and as the raw material for the planned *"generalise the Crossplane/Upjet
> ForceNew-rename migration pattern"* spike — not as a drop-in reusable library. Every mutating
> script is fail-closed (revision identity + normalized-spec hashes, human-gated diffs, break-glass
> over stdin, state-aware recovery). No secrets are embedded (passwords/tokens are read via stdin).

## A — Reusable operational tooling

| Script | Purpose |
|---|---|
| `mint-rotator.sh` | Mint an independent ephemeral **orphan** admin rotator token from a break-glass session (path `auth/token/create`, no parent) → `/tmp/rotator-token` (0600). Prereq for the rotation. |
| `rotate-breakglass.sh` | Rotate the break-glass (userpass) password **and** path-revoke all tokens ever issued via its login path. Independent rotator, 5-state recovery model, positive+negative verification, no auto-rollback to the exposed password. |
| `probe-breakglass-rotation.sh` | READ-ONLY preflight: rotator independence/capabilities, exact invalid-credentials signature, environment. |
| `probe-config-automation.sh` | READ-ONLY: live `ok-config-automation` policy HCL, reconciler role binding, kubernetes auth mounts, okvc- policies. |
| `phase3-T6-verify.sh` | READ-ONLY provenance + end-state + no-reference (audit-only) verifier for the legacy-policy deletion. |

## B — Worked-example evidence (the gated A6 migration; do NOT re-run)

Each `*-apply.sh` is non-runtime-effective (applies a Composition revision, machine-verifies the
diff, human-gates); each `*-import/run/promote/terminate.sh` performs the reviewed runtime step.

| Step | Scripts | Proved |
|---|---|---|
| T1 Observe-import | `phase3-T1-apply.sh`, `phase3-T1-import.sh` | adopt the existing okvc- policy Observe-only (no create/rename) |
| T2 Takeover | `phase3-T2-apply.sh`, `phase3-T2-import.sh` | `["Observe"] → ["*"]` full management, no external mutation |
| 3C first ACTIVE + drift | `phase3-T3-apply.sh`, `phase3-T3-run.sh` | reconciler active; injected drift auto-restored; consumer intact |
| 3D-1 Orphan-prep | `phase3-T4-apply.sh`, `phase3-T4-promote.sh` | old MR → Observe + `deletionPolicy: Orphan`, still paused |
| 3D-2 Terminate | `phase3-T5-apply.sh`, `phase3-T5-terminate.sh` | remove old MR; external Vault policy preserved (Orphan) |
| 3D-3a Delete | `phase3-T6-delete-legacy-policy.sh` | delete legacy policy after a global no-reference proof |
| 3D-3b Steady state | `phase3-T7-apply.sh`, `phase3-T7-promote.sh` | canonical comments-only revision; no MR created/terminated |
| A6 policy tightening | `a6-policy-test.sh`, `a6-apply-narrow.sh` | narrow `ok-config-automation` to `okvc-*`; live reconciler write-path proof + auto-rollback |

## Provenance note

The effective legacy-policy delete and the effective policy narrowing happened during the successful
runs; subsequent edits to these scripts were hardening only and performed no further mutation. The
committed bytes here are the final hardened versions, not necessarily the exact bytes of each
effective run — see the acceptance record for the honest completion evidence.
