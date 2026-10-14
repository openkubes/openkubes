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
