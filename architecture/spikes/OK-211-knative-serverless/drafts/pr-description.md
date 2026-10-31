<!-- Draft PR description. Not opened; PR only after CP2 approval. -->

## OK-211 — Knative as an optional serverless & event-driven capability (spike)

Adds the spike folder `architecture/spikes/OK-211-knative-serverless/`. Nothing outside it is changed: no ADR, no ok-local, no Console, no workflows.

### What is in it

- `BRIEF.md`: the work order, committed unchanged.
- `REPORT.md` (B13 outline) and `MANAGEMENT-SUMMARY.md`.
- `evidence/00`–`09`, one file per phase, with raw data in `evidence/raw/` (`measurements.json` holds every series).
- A guarded `Makefile` with scripts for the VM, K3s, Knative install/upgrade, measurements and experiments. Only context `ok211`, only `127.0.0.1:6450`, kubectl from `.local/bin`, single node.
- Pins and checksums in `versions.env`.

### Proposed result: CONDITIONAL GO

All must criteria M1–M6 are met. M3 depends on three declarative derivation rules for server-side apply. Of the optional criteria, K1, K3 and K4 are met, K2 in part, and K5 is not (perpetual drift on `pingsource-mt-adapter`). The decision belongs to the three-way review.

### Highlights and findings

- Cold start, cached image: median 1347 ms. Scale-to-zero ≈ 95 s. Autoscaling 0 → 6 pods in 9 s, no errors.
- Upgrade 1.23 → 1.24 under load: 0/476 errors, 0 events lost after `202`.
- High-severity findings:
  - F1: SSA conflicts on runtime-owned fields.
  - F2: kube-router NetworkPolicy does not cover new pods for ≥ 10 min.
  - F3: InMemoryChannel loses in-flight events.

### How to review

- Start with `MANAGEMENT-SUMMARY.md`, then `REPORT.md` §14 (findings) and §17 (criteria).
- Every claim links to an evidence file, and each evidence file lists its deviations from the brief.
- Reproduction: `REPORT.md` §19.

### Checks run

- `make lint` (shellcheck, yamllint; kubeconform not installed)
- `make scan-secrets` and `make scan-history`
- `make test-guard`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
