# OK-205 — Beta 1.1 reviewed FAQ manifest (draft)

Status: **proposal / not approved for publication**. The current Beta 1 Lite JavaScript remains the production source of truth until the FAQ loader, validators, golden tests, independent review and release approval are complete.

## Current implementation baseline

Source: [website/assets/ok-ai-lite-preview.js](../assets/ok-ai-lite-preview.js).

- Four exact normalized question variants map to two static, reviewed answer texts.
- Unknown inputs receive the fixed refusal. Answers include a pinned documentation link.
- No LLM, retrieval, external request on question submission or Kubernetes execution.

## Proposed schema (review contract)

Store future approved content in a machine-readable UTF-8 JSON manifest, with fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `schema_version` | yes | Schema version, initially 1 |
| `question_id` | yes | Stable identifier for a single intended claim |
| `variants` | yes | Explicit accepted phrases, unique after canonical normalization |
| `answer` | yes | Exact reviewed user-facing text, never composed speculatively |
| `sources` | yes | One or more claim-level `repository`, `path`, immutable `commit_sha`, `url` pointers |
| `review.owner` | yes | Named human reviewer |
| `review.reviewed_at` | yes | Date of evidence and answer review |
| `review.review_due` | yes | Next revalidation date |
| `review.status` | yes | `proposed`, `approved`, `expired`, `rejected` |

Only `approved` and non-expired entries may be bundled. The build must fail closed for missing or invalid sources, duplicate variants, unsupported schema, or absent review approval. A URL resolving successfully is not proof the linked source supports every answer claim.

## Existing Beta 1 Lite questions to migrate (not yet migrated)

**ok-local-definition** — Answer: “OpenKubes Local (ok-local) is a fully automated local development environment provided by the OpenKubes project.”

Accepted phrases:
- What is OpenKubes Local?
- What is OK Local?
- What is ok-local?

**ok-local-availability** — Answer: “Yes. OpenKubes provides a fully automated local development environment called ok-local.”

Accepted phrase:
- Does OpenKubes provide a local development environment?

Pinned reference for both, already used in Beta 1 Lite:
`https://github.com/openkubes/ok-local/blob/60397cdb2630b0cd9cfbcb5d9a29fe2e38ce323e/docs/tutorial-basic.md`

**Important:** Pin and answer provenance have been inherited from the released implementation; every claim still requires explicit human review before a new Beta 1.1 manifest is approved.

## Proposed FAQ expansion backlog (questions only; NO approved answers)

| Priority | Candidate intent | Candidate documentation |
| --- | --- | --- |
| P0 | What prerequisites do I need for ok-local? | `ok-local/docs/tutorial-prerequisites.md` |
| P0 | How do I get started with ok-local? | `ok-local/docs/tutorial-basic.md` |
| P0 | How do I use CAPI in ok-local? | `ok-local/docs/tutorial-capi.md` |
| P1 | How is Crossplane used in ok-local? | `ok-local/docs/tutorial-crossplane.md` |
| P1 | How do I work with the management environment? | `ok-local/docs/tutorial-mgmt.md` |
| P1 | How do I set up the infrastructure tutorial? | `ok-local/docs/tutorial-infra.md` |
| P1 | Where is the local AI Web UI tutorial? | `ok-local/docs/tutorial-ai-webui.md` |
| P1 | Where can I find the ok-cluster architecture docs? | `ok-cluster/docs/architecture/` |
| P2 | How do ok-local and ok-cluster differ? | Requires evidence from BOTH repos and explicit scope review |

All rows above are research candidates, not published capabilities or supported FAQs. Extend toward 20–30 reviewed intents *only* where the source actually supports a concise, correct, non-misleading answer.

## Mandatory quality gates

1. JSON schema validation and strict question normalization/uniqueness checks.
2. Claim-to-immutable-commit source checks; human review of source meaning and subject.
3. Positive/negative golden fixtures including near matches and wrong-subject prompts; exact fallback refusal.
4. XSS/unicode/length input tests; keep `textContent` safe rendering.
5. Keyboard, focus, Escape, browser console and single-widget checks from [OK-206](https://kubernauts.atlassian.net/browse/OK-206).
6. Build + preview smoke tests on legacy homepage and `/ai/`, with Fetch/XHR zero-request assertion.
7. Independent owner review for merge, and a **separate explicit** production release approval.

No change to the published widget is authorized by this document.
