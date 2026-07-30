# kagent Standalone — OK-129

Documentation set for the **standalone kagent evaluation** on a dedicated lab
cluster. Goal: be able to *build, explain and operate* a self-contained kagent
environment on a customer's Kubernetes — installation, configuration, agent
authoring, day-2 operations, and the honest limits.

**Ticket:** [OK-129](https://kubernauts.atlassian.net/browse/OK-129) ·
**Branch:** `feat/kagent-standalone` · **Cluster:** `ok-kagent`

## What this is not

This set is deliberately **decoupled from the OpenKubes ADRs**. It does not
change a contract, does not commit the platform to anything, and does not
supersede existing work:

| Existing work | Relationship |
|---|---|
| OK-14 (Agentic AI PoC) | Compared kagent *against* OpenClaw. Here we do not compare — we master one tool. |
| OK-92 / ADR-Platform-021 (Profile A) | Runs kagent *behind* the read-only diagnostics contract, with a facade. Here kagent runs **without** facade and **without** contract schema. |
| ADR-Platform-015 (Agentic AI) | Its Agent Interface Contract v1 and its read-only rule do **not** govern this lab. That is why the lab gets its own cluster. |

Whether kagent enters OpenKubes — and in which role — is decided **after** this
work, on the evidence produced here.

## Documents

| Document | Purpose | Audience |
|---|---|---|
| [`reference.md`](reference.md) | What kagent is and how it is configured: architecture, CRD map, every configuration surface, agent authoring patterns, limits | Engineers, architects |
| [`runbook.md`](runbook.md) | Operational, copy-pasteable: install, verify, build an agent, day-2, troubleshoot, uninstall | Whoever is on the keyboard |
| [`evidence-protocol.md`](evidence-protocol.md) | The scenarios that must be *proven*, with pass criteria strict enough that a plausible-but-ungrounded result fails | Whoever signs off OK-129 |

Read `reference.md` to understand, `runbook.md` to do, `evidence-protocol.md` to
prove.

## Version baseline

| Item | Value |
|---|---|
| kagent version | `0.9.12` — latest stable 0.9 patch; 0.10 was still a release candidate when selected (checked 2026-07-30) |
| Charts | OCI, `ghcr.io/kagent-dev/kagent/helm/{kagent-crds,kagent}` |
| Project status | Solo.io, **CNCF Sandbox** — lowest maturity tier |
| API group | `kagent.dev/v1alpha2` (since 0.6); kmcp uses `kagent.dev/v1alpha1` for `MCPServer` |
| Database | PostgreSQL **only** (SQLite removed in 0.8) |

kagent's docs site documents **the latest release only**. Pin a version, and read
the [release notes](https://kagent.dev/docs/kagent/resources/release-notes)
before every upgrade — the 0.6→0.9 range contains several breaking changes.

## Language convention

EN-first here (repo), DE version on Confluence after review — same convention as
the rest of `docs/`.
