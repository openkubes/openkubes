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

## Second private A2A run after lab prompt deployment (2026-10-19)

Operator verified private Context Agent generation 3, both new prompt rules PRESENT, configured tools 0, Ready=True and Accepted=True with observedGeneration 3. This does **not** attest the complete effective runtime toolset or egress. The reviewed manifest diff affected only `spec.declarative.systemMessage` plus routine metadata. Only the private lab Agent was updated after explicit operator approval.

Operator ran one private case `definition-ok-local` with the same pinned index and source revision. Sanitized capture: `CAPTURED_PRIVATE`, 245 rendered characters, one cited source, `semantic_grounding=UNVERIFIED`. Local human review of the model response found that the original single-node claim disappeared, but it still attributed a production-mirroring infrastructure property to `ok-local` without explicit support from the cited snippet.

**V2 human semantic verdict: FAIL — claim-to-source subject attribution remains unsupported.** Exact same source ID `072f1d1e37b925fc`, revision `60397cdb2630b0cd9cfbcb5d9a29fe2e38ce323e`. Prompt hardening alone has therefore **not** resolved this release blocker. Do not repeat prompt-only tuning without a testable additional control.

### Next smallest actionable slice

1. Add a **source-role-aware retrieval selection / claim-review design spike** without changing production gateway or bypassing `structured_answer`; avoid relying on a model self-grade as a security gate.
2. Test that it distinguishes tutorial-subject facts from separately described `ok-local` facts, preserving original exact revision and source ID integrity.
3. Add negative cases for unsupported claims and explicitly record where automated structural validation is **insufficient**. Keep final human-reviewed semantic acceptance required before public exposure.
4. Separately complete public auth, abuse limits, telemetry redaction, effective tool/network boundary verification, and preview/release approvals.

**Public Beta HOLD.**
