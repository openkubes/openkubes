# Isolated Structured JSON Agent — Private A2A Lab (v0.1)

**Experimental only. No public endpoints, no changes to the existing
`openkubes-docs-agent`, no connection to the preview widget.**

## Why separate?

The running agent uses `docs-ollama` / `go` / the single remote MCP
`openkubes-docs-search.docs_search`. Its unrestricted Markdown output
sometimes violates formatting rules. This experiment uses a *distinct*
`openkubes-docs-agent-json` Agent identity to request JSON conforming to
the strict `structured_answer.schema.json` contract.

The manifest contains **only one Agent resource**. It does not overwrite the
shared `ModelConfig` or change any existing Agent. The lab profile uses the
same dedicated docs-only MCP and non-root restrictions.

## Offline validation — first

From `platform/ai/assistant`:

```sh
python3 -m unittest discover -s tests -v
kubectl --kubeconfig "$HOME/.kube/ok-kagent.yaml" \
  --context ok-kagent-admin@ok-kagent \
  -n openkubes-assistant apply --dry-run=server \
  -f kagent/openkubes-docs-agent-json.lab.yaml
```

This second command asks the cluster admission API to validate a *proposed*
manifest. It does not create a new Agent, but does require cluster access.
Inspect the YAML before considering any live application.

## Operator-controlled private deployment (NOT part of this PR)

Only after a separate explicit go-ahead, create the lab Agent:

```sh
kubectl --kubeconfig "$HOME/.kube/ok-kagent.yaml" \
  --context ok-kagent-admin@ok-kagent \
  -n openkubes-assistant apply \
  -f kagent/openkubes-docs-agent-json.lab.yaml
```

Verify the new Agent has its own identity, is accepted/ready, and has
only `docs_search`; verify existing `openkubes-docs-agent` is unchanged.
Do not expose ingress or Cloudflare routing.

With the operator's existing private kagent-controller port-forward to
`127.0.0.1:8083` running, test the isolated JSON Agent:

```sh
python3 -m public_beta.private_structured_a2a_probe \
  --index /tmp/openkubes-docs-index.json \
  --question "How do I install OpenKubes Local on macOS?"
```

Returns redacted JSON status and fixed rejection reason, **never raw model
text**. A rejected response is expected in early experiments.

Safe removal when no longer needed (requires operator approval):

```sh
kubectl --kubeconfig "$HOME/.kube/ok-kagent.yaml" \
  --context ok-kagent-admin@ok-kagent \
  -n openkubes-assistant delete agent openkubes-docs-agent-json
```

## Critical caveats

* The A2A probe independently queries a validated local index. It **does not**
  prove that the Agent invoked `docs_search` or used the same passages.
* The JSON contract validates shape and source IDs, not semantic support,
  command safety, or actual runtime retrieval provenance.
* The dedicated JSON prompt is not an enforceable model-side JSON mode.
  kagent's `inputModes`/`outputModes` do not imply schema enforcement.
* The model is instructed to abstain with an empty `steps` array; the parser
  intentionally rejects this payload rather than fabricating citations.
* No admission outcome or live JSON-response PASS is claimed in this PR.
* No public ingress, browser integration, cluster-wide change, or Public Beta
  release is authorized. Public Beta remains **HOLD**.
