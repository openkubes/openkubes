# OpenClaw — Agentic AI Backend

Agent backend behind the **Agent Interface Contract v1** (OpenAI Chat
Completions + Tool Calling) per **ADR-Platform-015**. Runs as a
single-replica, token-authenticated, stateless Deployment; registered in
Open WebUI as a selectable model (`openclaw/default`). Open WebUI owns the
enterprise layer (multi-user, OIDC, chat persistence); OpenClaw is a
replaceable implementation profile — any backend speaking Contract v1
(e.g. kagent) can substitute it.

It is also the first conversational consumer of the ADR-021 Read-Only Platform
Diagnostics Contract (OK-94). Kubernetes diagnostics enter OpenClaw only through
the provider-neutral MCP adapter; the consumer has no Kubernetes credential,
client binary, or RBAC.

**Status:** OK-15 Phase 1 plus OK-94 MCP consumer integration.
Phase 2 (Crossplane XRD `OpenClawInstance`, self-service) follows **only
after a Go from the OK-14 PoC** — see the implementation order in
[`docs/agentic-ai-poc-guideline.md`](../../../docs/agentic-ai-poc-guideline.md).

## Layout

```
platform/ai/openclaw/
├── Makefile                     # deploy/operate targets (see `make help`)
├── charts/openclaw/             # minimal hand-rolled chart (no official chart upstream)
├── crossplane/                  # XRD + Composition + Claim examples (platform path)
├── scripts/verify-mcp-consumer.py # rendered consumer boundary checks
├── evidence/                    # dated, credential-free validation records
├── images/openclaw-kubectl/     # historical OK-15 image; not used by the chart
└── .gitignore                   # keeps the generated gateway token out of git
```

## Crossplane (platform path)

Same pattern as `platform/ai/open-webui/crossplane`: deploy via Claim from
ok-mgmt instead of running Helm by hand. The chart is fetched as OCI from
GHCR — publish it once with `make chart-release` (and after chart changes).

```bash
cd crossplane
make token-secret       # once: gateway token as Secret on ok-mgmt (never in git)
make setup              # once: XRD + Composition on ok-mgmt
make deploy CLUSTER=ok-ai OLLAMA_ENDPOINT=http://<ollama-ip>:11434
make status CLUSTER=ok-ai
```

The direct-Helm Makefile targets in this directory remain the debug/dev
path; Crossplane is how the platform installs the component.

The chart now uses `ghcr.io/openclaw/openclaw` directly. The historical
OpenClaw+kubectl image and workflow remain only as OK-15 evidence and are not a
supported diagnostics path.

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
make verify-mcp-consumer        # render chart and verify MCP-only/no-credential boundary
make verify-mcp-live            # verify the same boundary after deployment
```

`connect-openwebui` sets `OPENAI_API_BASE_URL`/`OPENAI_API_KEY` on the
Open WebUI StatefulSet. Open WebUI treats these as PersistentConfig *seed*
values: they auto-configure **fresh** instances (cluster rebuilds); on
instances already configured via the Admin UI, the DB value wins.

## Guardrails (ADR-015 / guideline — enforced in the chart)

Single replica + `Recreate` (hardcoded) · token auth · no consumer RBAC ·
ServiceAccount token automount disabled · upstream image without kubectl · Exec
denied · exactly three allowlisted diagnostics tools through the MCP adapter ·
no PVC (stateless; emptyDir only — statelessness verified in OK-14) ·
`gateway.bind: lan` · `chatCompletions` endpoint explicitly enabled
(upstream default-disabled).

**Stop rule (guideline Part C):** write verbs or secrets in RBAC, a second
parallel backend, wire-format changes, new Skill Contracts, per-user auth →
escalate (new ADR + review), do not implement.

## References

- [OK-14](https://kubernauts.atlassian.net/browse/OK-14) · [OK-15](https://kubernauts.atlassian.net/browse/OK-15) · [OK-94](https://kubernauts.atlassian.net/browse/OK-94)
- [ADR-Platform-015 — Agentic AI](../../../architecture/decisions/ADR-Platform-015-agentic-ai.md)
- [ADR-Platform-021 — Read-Only Platform Diagnostics Contract](../../../architecture/decisions/ADR-Platform-021-read-only-platform-diagnostics-contract.md)
- [Implementation guideline](../../../docs/agentic-ai-poc-guideline.md)
- [OpenClaw docs](https://docs.openclaw.ai) · [Open WebUI ↔ OpenClaw](https://docs.openwebui.com/getting-started/quick-start/connect-an-agent/openclaw/)
