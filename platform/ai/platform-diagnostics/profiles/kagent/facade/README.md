# Diagnostics facade — OpenAPI → kagent shim

Makes kagent a **conformant provider** of the Read-Only Platform Diagnostics
Contract. It implements the `contract/openapi.yaml` **Draft implementation
scaffold** and, per request, invokes the `openkubes-platform-agent` (kagent),
then shapes the agent's output into the ADR-021-derived schema
(`RankedHypothesis` with
`counter_evidence_status`, `EvidenceRef` references-only, `provider_capabilities`).
Normative OpenAPI finalization remains in OK-89/OK-90.

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

The agent is invoked over A2A at `{KAGENT_BASE_URL}/api/a2a/{KAGENT_NAMESPACE}/{KAGENT_AGENT}`
(JSON-RPC 2.0, `message/send`; enabled by `declarative.a2aConfig` on the Agent).

| env | meaning | default |
|---|---|---|
| `KAGENT_BASE_URL` | kagent controller svc (A2A served here) | `http://kagent.kagent.svc.cluster.local:8083` |
| `KAGENT_NAMESPACE` | namespace the Agents are deployed in | `platform-diagnostics` |
| `KAGENT_AGENT` | agent to invoke | `openkubes-platform-agent` |
| `KAGENT_TOOLS_URL` | scoped read-only Kubernetes MCP server | `http://platform-diagnostics-tools.platform-diagnostics.svc.cluster.local:8084/mcp` |
| `KAGENT_TOKEN` | bearer for kagent, if enabled | _(unset)_ |
| `PROVIDER_NAME` | logical provider id for audit | `kagent` |
| `PROVIDER_CAPS` | JSON of capability flags (Talos vs RKE2 delta) | see `app.py` |

The facade holds **no Kubernetes credentials** — cluster access lives only in the
kagent tool-executor's ServiceAccount. The facade only talks to kagent.

## Run / build

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8080      # local

# Image: build MULTI-ARCH. A plain `docker build` on Apple Silicon produces an
# arm64-only manifest, which the amd64 cluster nodes reject with
# "no match for platform in manifest". Use buildx and push a manifest that
# includes the node architecture (--provenance=false keeps it to real platforms):
docker buildx build --platform linux/amd64,linux/arm64 --provenance=false \
  -t ghcr.io/openkubes/platform-diagnostics-facade:0.1.3 --push .
```
