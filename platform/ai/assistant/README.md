# OK-202 — OpenKubes Documentation Agent PoC

**Status:** experimental, retrieval-only. No deployment, kagent runtime integration or public API is claimed.

This is a small, dependency-free lexical retrieval baseline to validate source attribution and a dedicated kagent Agent manifest. It intentionally **does not** connect to Kubernetes, Ollama, or the internet at query time.

## Usage

Requires Python 3.10+:

```sh
cd platform/ai/assistant
python3 -m unittest discover -s tests -v
python3 indexer.py build --output /tmp/openkubes-docs-index.json
python3 indexer.py search --index /tmp/openkubes-docs-index.json --query "How do I start ok-local?"
```

Index creation contacts the public GitHub API/raw.githubusercontent.com. A reproducible index contains resolved commit SHAs, stable source IDs and SHA-256 digests. Only allowlisted repositories/files are requested; raw source is read-only and never executed. The index is a **local build artifact**, not committed. Do not expose the index builder on a network route.

This is deliberately a lexical scoring baseline, **not RAG production quality** and not a deployed MCP tool. For kagent, see `kagent/openkubes-docs-agent.yaml`: tool registration and model endpoint remain placeholders pending verification of installed CRD and MCP transport.

## Hard boundaries

- No cluster diagnostic tools, Kubernetes API access, or default kagent tool server.
- No private Confluence/Jira ingestion, credentials, API endpoints or customer documents.
- No browser-to-kagent or browser-to-Ollama access.
- Public allowlist is reviewed in `indexer.py`; GitHub SHA URLs are derived by the indexer, never by an LLM.
- Future public API must validate citation IDs against trusted retrieval results, redact telemetry, and enforce quotas.

## Implementation milestones

1. Establish 30+ question baseline and citation-support scoring.
2. Evaluate a search adapter (lexical vs hybrid retrieval).
3. Validate dedicated kagent version, MCP read-only retrieval transport and Ollama tool use in isolated test environment.
4. Add protected API, SSE streaming and verified citations.
5. Only then integrate MkDocs widget on preview.

Spec: https://kubernauts.atlassian.net/wiki/spaces/OpenKubes/pages/3168894977
Tracking: https://kubernauts.atlassian.net/browse/OK-202

## MCP retrieval adapter (experimental)

`docs_mcp.py` exposes exactly one tool, `docs_search(query, limit)`, using the
official Python MCP SDK. The adapter validates public source allowlists, SHA-256
passage integrity and pinned GitHub source URLs when loading the index.

```sh
cd platform/ai/assistant
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-mcp.txt
python3 -m unittest discover -s tests -v

export OPENKUBES_DOCS_INDEX=/tmp/openkubes-docs-index.json
python3 docs_mcp.py
```

The default transport is **stdio**, suitable for a local MCP client. To test
Streamable HTTP locally (not public):

```sh
OPENKUBES_MCP_TRANSPORT=streamable-http python3 docs_mcp.py
```

The default listener address is `127.0.0.1:8000`, with the MCP route `/mcp`.
The intended kagent remote profile points to an internal Kubernetes Service;
a container image, index volume mount, namespace, locked-down NetworkPolicy,
service binding and a real installed-kagent compatibility test are still needed.
The service must **never** be deployed merely by applying the illustrative
`kagent/docs-search-mcp.yaml` or exposed on a public ingress.

The manifest `kagent/openkubes-docs-agent.yaml` now references only the
`openkubes-docs-search` RemoteMCPServer and explicitly allowlists the
`docs_search` tool. It has no link to the cluster-diagnostics tools.
A tool declaration is **not** a successful tool invocation; this requires
runtime verification with the target kagent version and Ollama model.

**Caveat:** This first retrieval tool only returns passages. It does not yet
perform server-side answer citation verification or generate final responses.
The current MCP dependency range is a PoC compatibility range, not a
production lockfile.
