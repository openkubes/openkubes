# Private Semantic Review — operator-only lab

**Status: Draft private lab. Public Beta HOLD.** No public gateway, deployment, cluster mutation or production approval.

## Goal
The existing A2A probe verifies answer structure and source IDs, not semantic correctness. Capture ONE structurally accepted answer and exact cited same-request snippets in a PRIVATE local review packet for human claim-level assessment.

Review packet status starts PENDING_HUMAN_REVIEW; semantic_grounding remains UNVERIFIED. Do not post packet content in public logs, PR comments or CI.

## Offline tests
From platform/ai/assistant on this branch:

    python3 -m unittest discover -s tests -p 'test_private_semantic_review.py' -v
    python3 -m unittest discover -s tests -v

Seven focused new tests expected; total 163 expected on this branch. Not yet operator verified.

## Optional private live review — requires fresh operator consent
Prerequisites: reviewed running private Agent and tools/network boundaries; operator-established localhost-only controller port-forward at 127.0.0.1:8083; trusted pinned index. This script does not establish a port-forward.

Prepare a local private directory OUTSIDE any git repository or cloud-synced folder:

    umask 077
    mkdir -m 700 "$HOME/.openkubes-private-review"

Then from platform/ai/assistant, only after explicit consent for this single live A2A invocation:

    python3 -m public_beta.private_semantic_review \
      --index /tmp/openkubes-docs-index.json \
      --case-id definition-ok-local \
      --output-dir "$HOME/.openkubes-private-review" \
      --ack-private-review

The CLI prints fixed status metadata only; the new local 0600 JSON packet includes the question, validated rendered answer, exact cited snippets, case rubric, provenance digests and PENDING_HUMAN_REVIEW decision. The directory must be owner-owned and no more permissive than 0700, and may not be a symlink. Rejected raw model answers are never saved; existing packet files are never overwritten.

Human reviewer inspects all factual assertions against the cited snippets and marks PASS, FAIL or UNVERIFIED in a separate local record. Source-ID correctness is not evidence of claim support or proof of model context consumption.

## Remaining gates
Private operator-approved live semantic sample, negative-case review, effective runtime tool/network security, public authentication/abuse controls, redaction/retention policy, preview validation and explicit release authorization.

No public release or merge authorization is implied.
