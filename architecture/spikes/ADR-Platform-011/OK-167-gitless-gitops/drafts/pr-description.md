## Summary

This spike evaluates Argo CD v3.5.6 consuming manifests from private zot OCI repositories. The review found real isolation, TLS, packaging, secret-scanning and evidence defects. This revision repairs those defects, adds guarded reproduction targets and retains a fresh local run instead of relying on the original self-assessment.

**Proposed outcome: NO-GO under the unchanged B13 rule.** Unattended detection was **141 / 144 / 184s** at `120s + 60s` jitter. The third run exceeds the 180s window beyond the recorded sampling uncertainty. Functional convergence occurred, but AC4 and M1/M4 are not met. The original CONDITIONAL GO is withdrawn. The three-way review owns the adoption decision.

All repository changes remain under `architecture/spikes/ADR-Platform-011/OK-167-gitless-gitops/`. Production profiles, ADRs and `.github/workflows/` are unchanged. The supplied German brief remains unchanged; revised code, comments, docs and publication text are English.

## Review handoff

The spike deliverables and review remediation are ready for Arash Kaffamanesh's review. No
further implementation is pending from Daniel for this evaluation handoff. The next action
is Arash's review of the report/evidence and a decision on accepting the spike outcome and
scoping further work. The proposed NO-GO and documented gaps remain unchanged. The PR stays
a draft; this handoff grants no adoption approval.

## Changes

- Validate the entire loopback API authority and reject kubeconfig proxies, plugins and external credential/CA paths; enable and verify Argo CD API TLS.
- Package an extracted Git tree after a complete source comparison, including ignored and index-hidden files; normalize archive permissions and independently compare fetched bytes with Git.
- Scan immutable staged blobs separately from working files, narrow placeholder exemptions, check binary credential paths, use stdin for passwords and remove the password-printing target.
- Add guarded auth/CA failures and recovery, structure negatives, TLS/webhook, signing, offline transfer, self-heal and outage experiments. Preserve push-phase timings, t0–t4 and TIMEOUT records.
- Correct unsupported timings, GC chronology and structural/security overclaims. Set `GTAR=tar` in the inactive Ubuntu CI example.

## Results

| Criterion | Revised assessment |
|---|---|
| AC1 | MET: verified registry TLS, auth/authz and referrers; V7 event caveat retained |
| AC2 | MET: deterministic one-layer packaging; fetched plain/signed/Kustomize bytes match Git |
| AC3 | MET: exact digest, Healthy, Deployment plus Service |
| AC4 | NOT MET under B9's timing requirement: T1 run 3 exceeded the window |
| AC5 | MET by the revised Confluence report linked below |
| M1 / M4 | NOT MET because AC4's timing requirement failed |
| M2 / M3 | Supported by the bounded secret checks, compatible Secret shape and byte-level provenance checks |
| K1 / K2 | NOT MET: no native zot CloudEvent handler or OCI signature gate |
| K3 / K4 | MET locally: deterministic layers; signed digest/referrer preserved and verified after transfer |

Other retained measurements: requested refresh detection 0/0/1s at whole-second resolution; self-heal 1.079s; cache-cold outage recovery 168.400s without refresh after registry restoration. Retained tag and digest Applications stayed populated over 560s. Three package/authenticate/push totals were 240/194/198ms. These are observations on one laptop, not benchmarks or a capacity model.

## Validation and evidence

- 39 adversarial regression cases passed; shellcheck, yamllint and actionlint passed.
- Registry negative checks require actual authorization rejection, not arbitrary network failure. Wrong credentials and removed CA produced 401/x509 errors and recovered.
- Signed bundle verification and recursive local transfer passed. A digest with neither referrers nor a legacy signature tag failed verification while Argo CD still synced it.
- The history audit compares eight local credential/password literals and private-key bodies through its recorded head; staged/worktree scanning covers the revision. These bounded checks do not prove the absence of every possible secret format.
- Current runtime and provenance checks passed before teardown. **`make verify` does not grade the latency series.** Only `ok167` was deleted; `wjax-demo` remains and test ports are closed.

One read-only diagnostic violated the isolation process: the caller did not inherit KUBECONFIG from `make guard`, fell back to its default configuration and failed authentication. No mutation or secret output occurred. It is explicitly documented; `make zot-status` now keeps the guard and read in the same exported environment. All cluster mutations used guarded Make targets.

Current evidence: [review remediation index](https://github.com/openkubes/openkubes/blob/spike/OK-167-gitless-gitops/architecture/spikes/ADR-Platform-011/OK-167-gitless-gitops/evidence/12-review-remediation.md). Historical documents 00–11 are labelled and corrected.

## Reproduction and limits

Use the ordered commands in [README](https://github.com/openkubes/openkubes/blob/spike/OK-167-gitless-gitops/architecture/spikes/ADR-Platform-011/OK-167-gitless-gitops/README.md): `make install`, the named `exp-*` targets, `offline-transfer DIGEST=...`, `verify`, then `down`. Cluster operations must remain in guarded Make targets.

S-D, Q1.e, Q3.a, Q3.d and Q3.e remain NOT RUN. No production Vault/VSO integration, scale, Git-source latency, disconnected convergence or zot-hosted workload-image pull is claimed. Digest pins still require tested retention/immutability; the original GC chronology was corrected and does not prove physical deletion of the specific blob. Signature enforcement and a refresh bridge remain proposed work.

- [Confluence report](https://kubernauts.atlassian.net/wiki/spaces/OpenKubes/pages/3179446273)
- [Jira OK-167](https://kubernauts.atlassian.net/browse/OK-167) — existing comment 15222 updated; status unchanged
- [Original review](https://github.com/openkubes/openkubes/pull/462#pullrequestreview-5711390080)

No approval or merge was performed. The PR remains a draft.
