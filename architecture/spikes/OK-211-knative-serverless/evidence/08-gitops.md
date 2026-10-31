# 08 — GitOps lifecycle

- Test IDs: G1–G4
- Date (UTC): 2026-10-31T13:53Z – 13:57Z
- Commit: `9878e51` plus the Phase 9 changes in this commit
- Environment:
  - VM `ok-knative-local`, K3s `v1.35.5+k3s1`, Knative `1.24.0`.
  - cert-manager `v1.21.3` and Traefik `v3.7.16`, both from Phase 7.
  - Field managers: `knative-release`, `cert-manager-release`, `traefik-chart`, `ok211`.

## Steps

```bash
make -C architecture/spikes/OK-211-knative-serverless diff LABEL=before   # kubectl diff --server-side on every set, current state vs repo
make -C … gitops-reapply                                                  # second apply of everything, in install order
make -C … diff LABEL=after
make -C … exp-G2                                                          # minimal ksvc, client- vs server-side diff, defaulted fields
```

The own desired state is [gitops/current-set.txt](../gitops/current-set.txt), 15 files. Variants of the same object are left out:

- `podinfo.yaml` vs `podinfo-fastdown.yaml`;
- the S8 split steps;
- the X1 services, deleted on purpose.

The release side uses the files as the apply sends them, that is the derived files from Phase 4 (rules B, B2, B3).

## Observed

### G1 — declarative re-apply and drift ([raw/g1-diff-before-20261031T135358Z.txt](raw/g1-diff-before-20261031T135358Z.txt), [raw/g1-diff-after-20261031T135503Z.txt](raw/g1-diff-after-20261031T135503Z.txt), [raw/g1-reapply-steps.log](raw/g1-reapply-steps.log))

| Set (field manager) | Diff before re-apply | Re-apply | Diff after |
|---|---|---|---|
| Knative release, 7 files (`knative-release`) | 6 clean; **`eventing-core.yaml` differs** | `knative.sh install 1.24`: no conflict (rules B, B2, B3 active), overrides re-patched | **`eventing-core.yaml` differs again** |
| cert-manager (`cert-manager-release`) | clean | applied | clean |
| Traefik, rendered chart (`traefik-chart`) | clean | applied | clean |
| Own set, 15 files (`ok211`) | 14 clean; `apps/eventing/base.yaml` differs: PingSource `ok211-ping` was deleted for X4 | applied, PingSource recreated | **all clean** |

**Finding — perpetual drift on `pingsource-mt-adapter`:**

- The release manifest defines its env list in a fixed order, including `POD_NAME`.
- The ping source controller rewrites the list in its own order and **without `POD_NAME`**.
- Each release apply restores the manifest version, and the controller then rewrites it again.

Observed during the re-apply:

| | Before | After |
|---|---|---|
| `generation` | 6 | 8 |
| `deployment.kubernetes.io/revision` | 6 | 8 |

- The two ReplicaSets from the upgrade (created 2026-10-31T09:26:17Z) were reused: revision 7 has the manifest template with `POD_NAME`, revision 8 the controller's template without it.
- So **every release sync rolls the ping adapter twice**.
- The server-side diff never becomes clean. A GitOps tool with self-heal would keep "fixing" it.
- Rule B3 (Phase 4) removes only the values of four env entries and `replicas`.
- Two ways out:
  - a fourth derivation rule that leaves `spec.template.spec.containers[0].env` of this Deployment to the controller;
  - `ignoreDifferences` on that path in Argo CD.

**Order** (as a proposal for Argo CD sync waves). It follows from the install order that worked, and from the webhooks (`failurePolicy: Fail`, X4) that must answer before dependent objects are written.

| Wave | Content | Why |
|---|---|---|
| −3 | `serving-crds`, `eventing-crds`, cert-manager CRDs (in its manifest) | every later object needs its type |
| −2 | `serving-core` (wait for `webhook` and `controller` Available) | `config-*` and every `serving.knative.dev` object pass the `Fail` webhooks |
| −1 | `kourier`, then the `config-network`/`config-domain` merge patches; `eventing-core` (wait for `eventing-webhook`), `in-memory-channel`, `mt-channel-broker`; cert-manager, then its issuers once its webhook answers | the networking layer must exist before the ingress class is set; the broker class needs the IMC |
| 0 | tenant namespaces, RBAC, NetworkPolicies, ksvc, Broker, Trigger, PingSource | workloads |
| PostSync | Knative post-install Jobs (`generateName`, created, not applied) | storage version migration after an upgrade |

In Argo CD this needs:

- the derivation rules B/B2/B3, or the equivalent `ignoreDifferences` for webhook rules, aggregated ClusterRole rules and the adapter fields;
- the env list of `pingsource-mt-adapter`;
- `kourier.spec.type` while N2 is active (Phase 7);
- `ServerSideApply=true`, so the manifests are applied as here.

### G2 — defaulting drift ([raw/g2-defaulting-20261031T135611Z.txt](raw/g2-defaulting-20261031T135611Z.txt))

The minimal ksvc `g2-podinfo` ([apps/serving/g2-podinfo.yaml](../apps/serving/g2-podinfo.yaml)) sets only an image and a port. It was applied server-side.

| Diff | Result |
|---|---|
| `kubectl diff` (client-side) | **exit 0**, no difference |
| `kubectl diff --server-side --field-manager=ok211` | **exit 0**, no difference |

Fields in the live spec that the manifest does not set, all added by the Knative defaulting webhook:

| Path | Live value |
|---|---|
| `spec.template.spec.containerConcurrency` | `0` |
| `spec.template.spec.timeoutSeconds` | `300` |
| `spec.template.spec.containers[0].name` | `user-container` |
| `spec.template.spec.containers[0].ports[0].protocol` | `TCP` |
| `spec.template.spec.containers[0].readinessProbe.tcpSocket.port` | `0` |
| `spec.template.spec.containers[0].readinessProbe.successThreshold` | `1` |
| `spec.traffic[0].latestRevision` | `true` |
| `spec.traffic[0].percent` | `100` |
| `metadata.annotations` | `serving.knative.dev/creator`, `serving.knative.dev/lastModifier` (`system:admin`) |

`managedFields`: only `ok211` (Apply) and `controller` (Update, subresource `status`).

What this means:

- With server-side apply and server-side diff the defaulted fields **do not show as drift**. The server applies the same defaulting to the dry-run object.
- `kubectl diff` without `--server-side` was also clean here. That is kubectl's merge against the live object, not a field-by-field comparison.
- A comparison of the raw manifest with the live object (the 8 paths above) does show drift.
- **Consequence for Argo CD**, per [Diff Strategies](https://argo-cd.readthedocs.io/en/stable/user-guide/diff-strategies/) (read 2026-10-31):
  - Legacy diff is the default. Server-Side Diff is "Stable (Since v3.1.0)" and opt-in, via `argocd.argoproj.io/compare-options: ServerSideDiff=true` or globally `controller.diff.server.side: "true"`.
  - "Server-Side Diff does not include changes made by mutation webhooks by default". `IncludeMutationWebhook=true` adds them.
  - So `ServerSideDiff=true` without `IncludeMutationWebhook` is the setting under which the defaulted fields above should not appear. Whether the Application really stays `Synced` without `ignoreDifferences` is the open G3 question.
- **Related finding from S8:** a ksvc with a fixed revision name is rejected on re-apply unless the defaulted `readinessProbe.successThreshold: 1` is written into the manifest. For GitOps manifests with named revisions, write that field out.

### G3 — Argo CD with the OK-167 OCI pipeline: **NOT RUN**

G3 is optional with a 2 h timebox, and it is the first item in the brief's drop order.

It would have meant installing Argo CD `v3.5.6` and zot and re-using `package-and-push.sh` from OK-167, only to answer one question: does an Application with `ServerSideDiff=true` stay `Synced` without `ignoreDifferences`?

G1 and G2 narrow that question down:

- With server-side diff the defaulted ksvc fields do not show (G2).
- The release side has a perpetual drift on `pingsource-mt-adapter` (G1), plus the fields of the three derivation rules. Argo CD needs `ignoreDifferences` for those, whatever its diff strategy.

The time went to the mandatory deliverables (Phases 10 and 11). Steps to close it:

1. Install Argo CD from the OK-167 pins.
2. Run zot plus `package-and-push.sh` for `apps/serving/g2-podinfo.yaml`.
3. Create an Application with `ServerSideDiff=true` and observe `Synced`/`OutOfSync` for 10 minutes.
4. Repeat with the Knative release as a second Application.

### G4 — Knative Operator as an alternative (documentation only)

Status, read from [github.com/knative/operator/releases](https://github.com/knative/operator/releases) on 2026-10-31:

- **`v1.24.0` is listed as "Latest", released 30 Oct.** The page shows no year, and the release notes are a placeholder. Before it came `v1.23.1` (01 Sep) and `v1.23.0` (04 Aug).
- The brief (status 2026-10-30) assumed the Operator was at 1.23.1, behind 1.24. That gap has closed since, but the Operator release is one day old and has no release notes yet.

| | YAML install (this spike) | Knative Operator |
|---|---|---|
| What lives in Git | ≈ 9 release files, derived per the rules B/B2/B3, plus merge patches for `config-*` | one Operator install, plus one `KnativeServing` and one `KnativeEventing` CR with `spec.version` and `spec.config` |
| Drift handling | the GitOps tool diffs every release object, which is where G1's perpetual drift and the SSA conflicts appear | the Operator reconciles the release objects. Git diffs only the CRs, so the conflicts from Phase 4 and G1 leave the GitOps diff |
| Upgrade | apply the next minor's files in order, run the post-install Jobs (U1) | change `spec.version`, and the Operator handles order and jobs |
| Rollback | not documented for YAML (U3) | documented, "Rollback to an earlier version" via `spec.version` (U3) |
| Cost | none beyond Knative | an extra controller with cluster-wide rights; it lags behind Knative releases (this time by about a week, with no notes yet) |
| Fit with ADR-001 (contracts, not components) | the profile pins exact manifests | the profile pins an Operator version and CRs; the release content is decided by the Operator |

For a GitOps-managed optional capability, the Operator removes most of what made the YAML path laborious here: the derivation rules, the drift on controller-owned fields, the order, the post-install Jobs and the rollback. In exchange it adds a component and a release lag. It was not installed or measured.

## Verdict

| ID | Verdict | Key value | Note |
|---|---|---|---|
| G1 | PASS — **FINDING** | Re-apply without conflicts; all own manifests, cert-manager and Traefik clean afterwards; **`eventing-core` never clean** (ping adapter env drift, 2 rollouts per sync) | sync-wave proposal above |
| G2 | PASS | 8 fields plus 2 annotations added by the webhook; server-side diff clean | Argo CD: `ServerSideDiff=true` (opt-in) |
| G3 | NOT RUN | — | optional, first in the drop order; steps listed |
| G4 | PASS (doc) | Operator `v1.24.0` released 30 Oct (Latest, notes pending); trade-offs listed | the brief's "1.23.1" is outdated |

## What this proves / What this does not prove

| Proves | Does not prove |
|---|---|
| The whole installation can be re-applied declaratively from pinned files without conflicts, given the three derivation rules | That it stays clean: the ping adapter drifts after every sync |
| Server-side diff hides Knative's defaulted ksvc fields | That Argo CD (`ServerSideDiff=true`) shows `Synced` (G3 not run) |
| An install order that works, as a sync-wave proposal | That Argo CD's wave and health handling works for Knative's webhooks and post-install Jobs |
| The Operator now has a 1.24.0 release | Anything about the Operator in practice |

## Deviations from BRIEF

1. **G3 NOT RUN** (optional, first in the drop order), with the reason and the steps listed.
2. **G4:** the brief's statement "Operator at 1.23.1" no longer holds. `v1.24.0` appeared on 30 Oct.
3. **G1's own set is curated** (`gitops/current-set.txt`): only the current variant of each object, without the X1 services that were deleted on purpose.
4. **`gitops.sh g2` failed twice before it ran.** First `render.sh`'s trailing `---` gave `yq` two documents, then `grep -v` on an empty diff ended a pipe with exit 1 under `pipefail`. Both were fixed. The ksvc `g2-podinfo` stays in `ok211-serving`.
5. **The re-apply also re-patched** `config-network` and `config-domain`, as `knative.sh install` does. Their values were unchanged.
