# OK-202: OpenKubes Documentation Agent — PoC validation

**Validated:** 2026-10-15. **Status:** Functional lab PoC passed; not production-ready or publicly available.

## Implemented architecture

The architecture diagram is embedded in [README.md](README.md).

- **UI:** internal kagent UI on `ok-kagent` (local port-forward only).
- **Agent:** `openkubes-assistant/openkubes-docs-agent`, kagent declarative Go runtime. Exposes only the `docs_search` tool.
- **Retrieval:** `openkubes-docs-search` MCP Deployment and internal Service, registered as a kagent `RemoteMCPServer`. Searches a read-only ConfigMap-mounted public-documentation index built by `indexer.py`, with allowlisted sources and GitHub revision-pinned citations.
- **LLM:** `ModelConfig/docs-ollama` uses `gpt-oss:20b` on a privately connected Ollama service in the separate `ok-infra` cluster. Its private endpoint is injected through a local, untracked configuration file.
- **Container:** private GHCR image deployed by verified immutable manifest digest using a namespace-local imagePullSecret. No Kubernetes write or diagnostic tools are attached to this agent.

## Observed functional tests

| Test | Observation |
| --- | --- |
| MCP and Agent readiness | Both Kubernetes Deployments were 1/1 Running; kagent Agent Ready=True and Accepted=True |
| MCP discovery | RemoteMCPServer Accepted=True and discovered exactly `docs_search` |
| In-cluster retrieval | Real MCP ClientSession through local port-forward completed initialize, tools/list and docs_search; retrieved ordered beginner-guide sections |
| Model availability | Temporary restricted Pod on `ok-kagent` queried private Ollama `/api/tags`; `gpt-oss:20b` appeared; Pod was removed |
| Positive AI test | In kagent UI, user asked how to install OpenKubes Local on macOS; agent called docs_search and produced stepwise instructions, fenced shell commands and clickable GitHub citations |
| Negative AI test | Agent queried docs_search for an unsupported Mars production-cluster request and did not produce invented installation commands in the observed response |

The negative test establishes absence of **documented evidence**, not an official support denial. Manually observed answers do not establish that every generated command is correct.

## Unresolved release gates

1. **Security:** The tested experimental distroless image reported 31 HIGH, 0 CRITICAL OS package findings (15 unique HIGH CVEs). A time-limited risk exception for the isolated **nonproduction** PoC was explicitly accepted through **2026-11-15**. This is **not** production approval. See [SECURITY-ASSESSMENT.md](SECURITY-ASSESSMENT.md).
2. **Answer integrity:** Compare every emitted installation command with its linked source, ensure revision-pinned links, prevent invented commands, and automate representative positive/negative and injection tests. Current citation verification is not performed server-side.
3. **Networking:** Test NetworkPolicy denial paths and agent egress/DNS boundaries, beyond mere pod readiness and local port-forward; keep the MCP Service private and no direct browser-to-Ollama connection.
4. **Operations:** Add managed pull credentials, vulnerability remediation/review, image provenance, resource/rate limits, logging controls and a protected public-facing API/widget before integrating into openkubes.org.

**Tracking:** [OK-202](https://kubernauts.atlassian.net/browse/OK-202). Keep release work in a reviewed PR.
