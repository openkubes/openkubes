# ADR-Platform-025 — A6 Ownership Migration Acceptance Record

**Scope:** ADR-Platform-025 item 13 amendment **A6** — move the reconciler-managed Vault policy of
the `VaultConfig` capability to the reserved `okvc-` identity prefix, so the `ok-config-automation`
policy can be scoped to `sys/policies/acl/okvc-*` and cannot touch admin policies.

**Status:** Migration **completed** on 2026-07-26. The live `vaultconfig.platform.openkubes.ai`
Composition runs on the canonical steady-state revision; the reconciler-managed policy identity is
`okvc-ok-robotics-sa-obs`; the legacy policy `ok-robotics-sa-obs` has been removed.

---

## Why a migration was needed

`upbound/provider-vault`'s `vault_policy` treats `metadata.name` as **ForceNew / immutable**. A
direct rename (`ok-robotics-sa-obs` → `okvc-ok-robotics-sa-obs`) was **refused** by the provider
(`AsyncUpdateFailure: requires replacing it`), not merely risky. Renaming by delete-then-recreate
would have risked a window with no valid policy for the live consumer. The migration therefore
followed a safe, gated key-rotation pattern: adopt the new identity alongside the old, prove it,
hand ownership over, retire and remove the old Crossplane object under Orphan semantics, and only
then delete the now-unreferenced legacy Vault policy.

## Identity and evidence

| Item | Value |
|---|---|
| Composition | `vaultconfig.platform.openkubes.ai` |
| Composition UID | `ecd72174-4ead-4126-bc70-52be5872f6c8` |
| Steady-state revision | `vaultconfig.platform.openkubes.ai-b7ea3c5` |
| Steady revision normalized spec SHA256 | `26618d5f64f311b16f51dea6949774e1b18854480ce68d49a0f2f9ca4b83c988` |
| Reconciler-managed policy (kept) | `okvc-ok-robotics-sa-obs` |
| okvc- policy content SHA256 (stable T5 → T7) | `cbbd0d8a3c57fcb46e7a6c0e107140f5fd370d4737413d9c9668598bbf62fbd6` |
| Legacy policy (deleted) | `ok-robotics-sa-obs` |
| Legacy Crossplane Policy MR (removed) | `ok-robotics-ee43e699198c` (uid `89913172-8357-417f-9b27-66eb5eafe568`) |

### Steady-state resource set — exactly 4 managed resources, UIDs stable across 3D-3b

| Kind | composition-resource-name | MR name |
|---|---|---|
| `Backend` (auth) | `authbackend` | `ok-robotics-05b190692d43` |
| `AuthBackendConfig` (kubernetes) | `authbackendconfig` | `ok-robotics-1cf8d3106f89` |
| `Policy` (vault, okvc-) | `policy-okvc-<role>` | `ok-robotics-f3f5cd82a670` |
| `AuthBackendRole` (kubernetes) | `role-<role>` | `ok-robotics-6cae6fef03f6` |

`crossplane.io/external-name` = `okvc-ok-robotics-sa-obs`, `managementPolicies: ["*"]`, no pause
annotation. Vault role `auth/kubernetes/ok-robotics/role/sa-obs` `token_policies` = `["okvc-ok-robotics-sa-obs"]`.

## Migration chain (revision suffixes)

| Step | Revision | What it proved |
|---|---|---|
| base | `32f8bda` | pre-migration (single legacy Policy MR) |
| T1 (Observe-import) | `ac6a028` | new okvc- MR adopts the existing okvc- policy Observe-only — no create, no rename, hash unchanged |
| T2 (Takeover) | `068e558` | okvc- MR `["Observe"] → ["*"]` — fresh full-management ReconcileSuccess, no create, no external mutation |
| 3C (first ACTIVE) | `81af7b7` | reconciler unpaused; a real injected drift on the okvc- policy is auto-restored; consumer stays healthy |
| 3D-1 (Orphan-prep) | `7c819f1` | legacy MR retired: `["Observe"]` + `deletionPolicy: Orphan`, still paused, not terminating |
| 3D-2 (Terminate) | `b79f9d5` | legacy block removed; MR terminates under Observe+Orphan; **external Vault policy preserved** (hash-equal) |
| 3D-3a (Delete) | — (Vault-only) | execution-time no-reference gate, then `vault policy delete ok-robotics-sa-obs`; okvc-/consumer intact (a later read-only re-verification with the expanded scanner set found zero current live references) |
| 3D-3b (Steady state) | `b7ea3c5` | canonical comments-only revision (relative to T5) promoted; **no composed MR was created, recreated, or terminated**; external Vault state + consumer Secret bytes unchanged (XR revisionRef/generation/resourceVersion/status updated as expected) |

Every mutating step ran under machine-enforced, fail-closed gates, including revision identity and
normalized-spec hashes, human-gated diffs, break-glass delivery over stdin, and state-aware
recovery. Emergency freeze was used where a confirmed runtime mutation required preserving the
state for inspection; the deliberate 3D-3a policy delete was never automatically restored.

## 3D-3a completion evidence (precise wording)

> 3D-3a is operationally evidenced by the successful T6 handoff marker, policy-hash continuity from
> T5, the verified okvc-only end state, and an audit-only scan showing zero live references,
> including 28 active persisted token accessors. The configured Vault file audit device did not
> yield a parseable delete entry during the later verification and therefore provided no additional
> corroboration.

**No-reference proof (audit-only re-verification, read-only):** zero live references to the legacy
policy from any Crossplane Policy MR, Kubernetes/userpass auth role or user, token role, identity
entity or group, or active persisted token (28 accessors live-checked). The affected `sa-obs` role
resolves to `default-service`; tokens issued by that role are therefore persisted and covered by
accessor enumeration. The verification does not claim enumeration of non-persisted batch tokens from
unrelated token issuers.

**Audit note:** the Vault file audit device (`/vault/audit/audit.log`) yielded **no parseable delete
entry** for `sys/policies/acl/ok-robotics-sa-obs` during the later verification. Possible
explanations include log rotation, audit enablement after the delete, or a query/format mismatch;
the cause was not established. This provided **no additional corroboration** and is recorded as such;
provenance rests on the consistent T6 handoff marker, the policy-hash continuity, and the
zero-live-reference end state.

## Honest tooling note

The **effective legacy-policy delete occurred during the successful 3D-3a run**. Subsequent changes
to `phase3-T6-delete-legacy-policy.sh` (ERR-trap-safe capture, split stdout/stderr with
endpoint-scoped empty-list classification, token-accessor race tolerance, allowed_policies_glob and
batch-token fail-closed checks) were **hardening only** and executed **no further delete** — a later
re-run correctly aborted with `DELETE_NOT_STARTED` on the idempotency guard. The record does not
claim that the final hardened script bytes were the exact bytes that performed the effective delete;
completion is evidenced by the successful T6 handoff marker, policy-hash continuity, the verified end
state, and the later read-only zero-reference verification.

## Runtime continuity

Throughout T1 → T7 the consumer's VSO stack stayed healthy (`VaultAuth/ok-robotics` +
`VaultStaticSecret/ok-observability-credentials` in namespace `ok-observability` on ok-robotics), and
the materialized Secret `ok-observability-credentials` was byte-unchanged across every step,
including the 3D-3b steady-state promotion (`consumerSecretUnchanged: true`).

## Follow-ups outside A6 migration completion

- **A6 negative-policy test** — prove `ok-config-automation` cannot write a non-`okvc-` policy. This
  remains an **ADR-025 acceptance blocker** even though the ownership migration itself is complete.
- **Break-glass credential rotation** — a break-glass password was exposed during the working
  session and must be rotated **before merge / before this session is considered closed**, not left
  as an open-ended Day-2 item.

(The T1–T5 and T6-steady transition Compositions were local, untracked migration artifacts. They
were removed from the working tree before the final commit and are not retained as canonical
repository content.)
