# kagent Standalone — OK-129

Documentation set for the **standalone kagent operations PoC** on a dedicated
lab cluster. The goal is deliberately narrow: install one pinned kagent release,
operate a useful cluster agent, exercise a safely bounded write flow, recover
the installation, and document the observed limits.

**Ticket:** [OK-129](https://kubernauts.atlassian.net/browse/OK-129) ·
**Branch:** `feat/kagent-standalone` · **Cluster:** `ok-kagent`

## What this is not

This set is deliberately **decoupled from the OpenKubes ADRs**. It does not
change a contract, does not commit the platform to anything, and does not
supersede existing work. The executable assets live under
[`research/kagent-standalone/`](../../research/kagent-standalone/README.md) rather
than under `platform/`, because placement in the platform tree carries
architectural meaning that a disclaimer cannot cancel: `platform/` is contracted,
ADR-governed work, and this is not. Adoption — if it happens — moves the assets
there together with an ADR, a contract and a named consumer.

| Existing work | Relationship |
|---|---|
| OK-14 (Agentic AI PoC) | Compared kagent *against* OpenClaw. Here we do not compare — we master one tool. |
| OK-92 / ADR-Platform-021 (Profile A) | Runs kagent *behind* the read-only diagnostics contract, with a facade. Here kagent runs **without** facade and **without** contract schema. |
| ADR-Platform-015 (Agentic AI) | Its Agent Interface Contract v1 and its read-only rule do **not** govern this lab. That is why the lab gets its own cluster. |

Whether kagent enters OpenKubes — and in which role — is decided **after** this
work, on the evidence produced here.

The following capabilities are not acceptance criteria for this PoC: a custom
MCP server, multi-agent orchestration, memory/pgvector, skills, OIDC, three-node
controller HA, and a minor-version migration. They are separate follow-up
questions, not prerequisites for learning to operate kagent well.

## The permission model is the deliverable people will ask about

kagent can be deployed here in two roles, chosen at install time from **one
config file** — read-only diagnosis, or additionally an approval-gated ConfigMap
write path scoped exactly to the evidenced `kagent-lab` namespace. RBAC, the write tool server and the
write Agent are generated from that file, so the documented boundary and the
deployed boundary cannot drift apart.

Where the boundary actually sits, in one sentence: **Kubernetes calls are executed
by the tool server's ServiceAccount, not by the Agent** — so `toolNames`,
`requireApproval` and the system prompt shape intent, and RBAC decides capability.

Two corollaries that are easy to overstate, so they are stated here in the form we
will use with a customer:

- **The generated operator Agent is approval-gated. The shared write tool server
  and its Kubernetes identity are not themselves protected by that approval
  policy.** `requireApproval` sits on that one Agent's tool reference; a second
  Agent could reference the same tool server without it. Making approval a hard
  capability boundary would require enforcement in the tool server or another
  server-side authorization mechanism, which does not exist upstream today.
- **No direct Secret, ServiceAccount or RBAC API permission is granted to the write
  identity.** That is a claim about permissions, not a proof that no indirect path
  exists: pod-template mutation on a Deployment, StatefulSet, DaemonSet or Job can
  reach existing Secrets or a more privileged ServiceAccount in the same namespace
  without calling the Secret API, and only admission control prevents it. That is
  one reason the renderable write surface is ConfigMaps only.

The renderer refuses everything wider — other namespace targets, workload kinds,
Services, Ingresses, Pod deletion, ungated writes, cluster-wide scope — as
candidate work.

Start at
[`research/kagent-standalone/access/README.md`](../../research/kagent-standalone/access/README.md);
`reference.md` §7.1 has the same thing in context.

## Documents

| Document | Purpose | Audience |
|---|---|---|
| [`reference.md`](reference.md) | Architecture and feature reference; advanced features are background, not PoC scope | Engineers, architects |
| [`runbook.md`](runbook.md) | Install, verify, operate, restart, troubleshoot, and uninstall | Whoever is on the keyboard |
| [`evidence-protocol.md`](evidence-protocol.md) | The small set of operating scenarios that must be proven | Whoever signs off OK-129 |

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
