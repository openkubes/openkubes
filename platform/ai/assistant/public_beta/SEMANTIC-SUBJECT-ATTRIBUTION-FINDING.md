# Semantic finding: subject attribution (private lab)

**Status: HUMAN REVIEW FAIL / fix unverified. Public Beta HOLD.**

## Reproducible evidence

Private review case: `definition-ok-local`. Pinned source:
- Repo: `openkubes/ok-local`
- Path: `docs/tutorial-basic.md`
- Revision: `60397cdb2630b0cd9cfbcb5d9a29fe2e38ce323e`
- Source ID: `072f1d1e37b925fc`

The source says **this tutorial** runs KubeVirt on a single node. Separately, the OpenKubes project provides an automated local development environment called `ok-local`. The real context-only model answer attributed a single-node, production-like topology to `ok-local`; the cited snippet does not explicitly establish either property for `ok-local`.

**Human review verdict:** `FAIL` for claim-to-source support and precise subject attribution. Valid source ID and successful JSON contract do not mean semantic correctness.

## Change

The private context Agent lab manifest now explicitly instructs the model to maintain the original subject of each claim and to omit unsupported cross-subject relations. This is prompt hardening, **not proof of semantic enforcement**.

A new offline test proves the documented **validator gap** by showing an artificially misattributed claim may still pass the existing structural schema/source-ID checker. The test also checks the presence of the improved prompt guard and the ability to structure a narrower supported statement. A passing test does not make the model semantically safe.

## Operator checks (no deployment)

From `platform/ai/assistant` on branch `fix/ok-ai-subject-attribution-semantic-lab`:

    python3 -m unittest discover -s tests -p 'test_subject_attribution_evidence.py' -v
    python3 -m unittest discover -s tests -v

Expected 3 focused tests, approximately 166 total if 163 prior tests remain unchanged. Tests not yet operator-verified.

## Required follow-up before retesting a live agent

1. Review this prompt-only YAML diff and its security implications.
2. Determine which manifest revision is actually running in the PRIVATE context Agent. Updating Git does not update deployed prompts automatically.
3. Only with explicit operator approval for a **private lab** change should the revised manifest be deployed. Do not apply blindly; first diff desired vs live Agent and validate actual effective runtime tools and network policies.
4. After independent authorization, repeat **one** private semantic-review A2A case against that exact deployed revision, then manually evaluate every claim in the new locally saved packet.
5. Record PASS/FAIL/UNVERIFIED as sanitized metadata in the PR. Preserve the original FAIL as evidence rather than rewriting its verdict.

No public endpoint, command-rendering, Kubernetes mutation or beta release is authorized by this PR.
