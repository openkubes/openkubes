# OpenClaw — Optional Agent Backend

OpenClaw is an optional agent implementation behind the OpenKubes **Agent Interface Contract**. The repository describes a token-authenticated, stateless deployment, integrated with Open WebUI as an agent-backed model.

## Architecture and boundaries

- Open WebUI provides the chat-facing interface; agent runtimes remain replaceable behind a defined contract.
- Platform diagnostics are accessed through the bounded, read-only diagnostics/MCP interface, not through inherited administrator credentials.
- Agent integrations must respect explicit authorization, tool boundaries and evidence collection.
- Experimental PoC work and roadmap entries must not be interpreted as a generally available autonomous production operations service.

## Source-owned documentation

- [OpenClaw component README](https://github.com/openkubes/openkubes/blob/main/platform/ai/openclaw/README.md) — status, architecture, security controls and component-specific deployment guidance.
- [Agentic AI implementation guideline](https://github.com/openkubes/openkubes/blob/main/docs/agentic-ai-poc-guideline.md).
- [ADR-Platform-015 — Agentic AI](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-015-agentic-ai.md).
- [ADR-Platform-021 — Read-Only Platform Diagnostics](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-021-read-only-platform-diagnostics-contract.md).
- [Agentic Operations](agentic-operations.md) — broader reference architecture and governance.

**Operational note:** Only run agent deployments after reading the current component README and validating target-cluster access and security requirements.
