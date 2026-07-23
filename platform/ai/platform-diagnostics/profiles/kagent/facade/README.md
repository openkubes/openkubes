# Diagnostics facade — OpenAPI → kagent shim

Makes kagent a **conformant provider** of the Read-Only Platform Diagnostics
Contract. It implements `contract/openapi.yaml` verbatim and, per request,
invokes the `openkubes-platform-agent` (kagent), then shapes the agent's output
into the normative ADR-021 schema (`RankedHypothesis` with
`counter_evidence_status`, `EvidenceRef` references-only, `provider_capabilities`).

```
OpenClaw ─(MCP adapter)─► facade  ─(kagent A2A/API)─►  openkubes-platform-agent
   consumer               (this)                         │ delegates to specialists
                            │                             ▼
                            └── shapes ADR-021 schema ◄── Kubernetes API (read-only SA)
```

This is a **skeleton**: the HTTP surface, schema, config and wiring are real; the
kagent invocation and the agent-output→schema mapping are marked `TODO` and need
the live kagent endpoint (from OK-14) plus a couple of prompt/response iterations.
It runs and serves schema-valid **stub** responses so consumers and contract tests
1/3/5/6 can be exercised before kagent is fully wired.

## Config (all env; endpoints are Provider Values from ok-cluster)

| env | meaning | default |
|---|---|---|
| `KAGENT_BASE_URL` | kagent API/A2A base (in-cluster svc) | `http://kagent.kagent.svc.cluster.local:8083` |
| `KAGENT_AGENT` | agent to invoke | `openkubes-platform-agent` |
| `KAGENT_TOKEN` | bearer for kagent, if enabled | _(unset)_ |
| `PROVIDER_NAME` | logical provider id for audit | `kagent` |
| `PROVIDER_CAPS` | JSON of capability flags (Talos vs RKE2 delta) | see `app.py` |

The facade holds **no Kubernetes credentials** — cluster access lives only in the
kagent tool-executor's ServiceAccount. The facade only talks to kagent.

## Run / build

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8080      # local
docker build -t ghcr.io/openkubes/platform-diagnostics-facade:dev .
```
