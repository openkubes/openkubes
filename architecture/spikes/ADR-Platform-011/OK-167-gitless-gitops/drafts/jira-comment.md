**Ready for review — handoff to Arash Kaffamanesh (2026-10-30).**

Arash, please review the linked report, PR and retained evidence. D1–D3, the review remediation
and English documentation are complete for the current evaluation. No further implementation
is pending from Daniel Santiago Gawenda before your review. Feedback or an explicitly scoped
follow-up may create new work. The next action is your review/decision; the proposed NO-GO
remains unchanged and this is not an adoption approval.

Please confirm the spike outcome, decide how to address the detection-window failure, and
select any signature-enforcement, retention or refresh follow-ups that should be scoped and
assigned. No follow-up tickets, merge or Jira status transition are created by this handoff.

**Review remediation complete — proposed decision: NO-GO under the unchanged B13 criteria.** This replaces the earlier CONDITIONAL GO assessment.

- [Draft PR #462](https://github.com/openkubes/openkubes/pull/462)
- [Revised Confluence report](https://kubernauts.atlassian.net/wiki/spaces/OpenKubes/pages/3179446273)
- [Raw evidence index](https://github.com/openkubes/openkubes/blob/spike/OK-167-gitless-gitops/architecture/spikes/ADR-Platform-011/OK-167-gitless-gitops/evidence/12-review-remediation.md)

**Acceptance and decision:** AC1–AC3 pass. AC4 is NOT MET under B9: three unattended detections took **141 / 144 / 184s** at `120s + 60s` jitter. Run 3's last nonmatching request began at t0+183.299s and its first match at t0+184.374s; the recorded sampling uncertainty does not explain the overrun. M4 and consequently M1 are NOT MET, so B13 requires NO-GO. Functional convergence in all three trials does not override that rule. AC5 is the revised report linked above. M2/M3 are supported within the documented checks; K1/K2 remain NOT MET and K3/K4 pass locally.

**Repairs:** exact loopback authority and restrictive kubeconfig checks; Argo CD API TLS; Git-snapshot packaging and fetched-byte provenance verification; normalized archive modes; staged-blob scanning and narrow placeholder handling; stdin password handling; guarded experiment/restoration targets; retained timing data; inactive CI GNU tar fix. All revised code, comments, documentation and publication text are English. Only the spike directory changed; production profiles and ADRs did not.

**Retest evidence:** 39 regression cases passed, plus shellcheck/yamllint/actionlint. Registry TLS/auth/authz/referrers, actual 401/x509 failures and recovery, populated Applications, negative layer cases, signing, unsigned synchronization and signed offline transfer were rerun. Final V7 recorded search/trust active but no new smoke event; this is an explicit allowed caveat. Self-heal was 1.079s, outage recovery 168.400s without refresh after restoration, retained tag/digest availability 560s, and package/authenticate/push totals 240/194/198ms. Whole-second requested-refresh detection was 0/0/1s. These local observations do not establish production scale.

**Corrections to earlier claims:** the original 182s sample was not demonstrated to be within 180s; unsupported package/recovery numbers are withdrawn. The GC log preceded the Q4.c push and does not prove deletion of that specific blob. zot's health-route exemption is supported by pinned source/local probes, not a production health audit. Structure limits also include total-layer, extraction and symlink checks. CA restoration used a repo-server restart and does not prove restart is mandatory. Prefix credentials work locally; production Vault/VSO remains untested. Legacy signature tags differ from the bundle referrers preserved by recursive transfer.

**Process deviation:** one ad-hoc read after `make guard` lacked an exported caller KUBECONFIG and failed authentication against the caller's default configuration. No mutation or secret output occurred. This isolation violation is documented; the replacement `make zot-status` runs guard and read in the same environment. All cluster mutations used guarded Make targets. The ok167 cluster has been deleted; wjax-demo remains.

S-D, Q1.e, Q3.a, Q3.d and Q3.e remain NOT RUN. No air-gapped envelope, production retention policy, signature promotion gate, refresh bridge or workload-image availability is claimed. Resolve and retest the detection-window failure before reconsidering adoption. Further work remains subject to the three-way review; no new tickets, approval, merge or status transition were performed.
