# OpenClaw — Agentic AI Backend

Agent backend behind the **Agent Interface Contract v1** (OpenAI Chat
Completions + Tool Calling) per **ADR-Platform-015**. Runs as a
single-replica, token-authenticated, stateless Deployment; registered in
Open WebUI as a selectable model (`openclaw/default`). Open WebUI owns the
enterprise layer (multi-user, OIDC, chat persistence); OpenClaw is a
replaceable implementation profile — any backend speaking Contract v1
(e.g. kagent) can substitute it.

**Status:** OK-15 Phase 1 (Makefile + Helm, PoC-grade).
Phase 2 (Crossplane XRD `OpenClawInstance`, self-service) follows **only
after a Go from the OK-14 PoC** — see the implementation order in
[`docs/agentic-ai-poc-guideline.md`](../../../docs/agentic-ai-poc-guideline.md).

## Layout

```
platform/ai/openclaw/
├── Makefile                     # deploy/operate targets (see `make help`)
├── charts/openclaw/             # minimal hand-rolled chart (no official chart upstream)
├── images/openclaw-kubectl/     # official image + pinned kubectl (Cluster Inspection skill)
└── .gitignore                   # keeps the generated gateway token out of git
```

CI: `.github/workflows/build-openclaw-kubectl.yaml` builds and pushes the
image to `ghcr.io/<owner>/openclaw-kubectl` on changes under `images/`
(same pattern as the capi-platform-runner workflow). GHCR is the primary
registry (OK-15 decision; Harbor deferred) and is the default in
`charts/openclaw/values.yaml`. Until the first CI push lands, the manually
pushed Docker Hub `kubernautslabs/openclaw-kubectl` serves as bootstrap:
`--set image.repository=kubernautslabs/openclaw-kubectl`.

## Provider Values (private — not in this repo)

Real endpoints live in the private infrastructure repo, per platform
convention (see `platform/ai/open-webui/values.yaml`):

```bash
make preflight install validate OLLAMA_URL=http://<ollama-ip>:11434
```

Everything else (namespace, model, numCtx, timeouts, registry) is a
Provider Value per guideline Part C — adjust freely in
`charts/openclaw/values.yaml`.

## Deploy & connect

```bash
make preflight OLLAMA_URL=...   # nodes, Ollama reachability, Open WebUI env check
make install   OLLAMA_URL=...   # token generated to .token (gitignored), helm install
make validate                   # in-cluster /v1/models + completion test
make connect-openwebui          # auto-register in Open WebUI (env seed, fresh instances)
make connect-info               # or: manual values for the Admin UI
make verify-kubectl             # RBAC guardrails: reads OK, secrets/writes denied
```

`connect-openwebui` sets `OPENAI_API_BASE_URL`/`OPENAI_API_KEY` on the
Open WebUI StatefulSet. Open WebUI treats these as PersistentConfig *seed*
values: they auto-configure **fresh** instances (cluster rebuilds); on
instances already configured via the Admin UI, the DB value wins.

## Guardrails (ADR-015 / guideline — enforced in the chart)

Single replica + `Recreate` (hardcoded) · token auth · read-only RBAC
(`get/list/watch`, **secrets excluded**, verified by `make verify-kubectl`)
· no PVC (stateless; emptyDir only — statelessness verified in OK-14) ·
`gateway.bind: lan` · `chatCompletions` endpoint explicitly enabled
(upstream default-disabled).

**Stop rule (guideline Part C):** write verbs or secrets in RBAC, a second
parallel backend, wire-format changes, new Skill Contracts, per-user auth →
escalate (new ADR + review), do not implement.

## References

- [OK-14](https://kubernauts.atlassian.net/browse/OK-14) · [OK-15](https://kubernauts.atlassian.net/browse/OK-15) (source of truth for tasks/acceptance criteria)
- [ADR-Platform-015 — Agentic AI](../../../architecture/decisions/ADR-Platform-015-agentic-ai.md)
- [Implementation guideline](../../../docs/agentic-ai-poc-guideline.md)
- [OpenClaw docs](https://docs.openclaw.ai) · [Open WebUI ↔ OpenClaw](https://docs.openwebui.com/getting-started/quick-start/connect-an-agent/openclaw/)
