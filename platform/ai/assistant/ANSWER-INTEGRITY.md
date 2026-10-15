# OK AI Answer Integrity — strict offline prototype

This module is **not wired to a live gateway**. It is a deliberately conservative experiment to expose answer-integrity problems before public release.

## Local test

From `platform/ai/assistant`:

```sh
python3 -m unittest discover -s tests -v
```

The `answer_integrity.validate_answer(answer, retrieval, index)` function:
- validates the public source index against the existing allowlist, integrity hashes and pinned URLs;
- checks that retrieval hits match documents in the trusted index;
- accepts only Markdown links to URLs included in that retrieval;
- accepts fenced `bash` / `sh` command blocks only when their **exact block content** occurs in a retrieved passage;
- fails closed on missing/foreign links, unrecognized code fences and unsupported markup.

It does not run commands, make API calls, connect to a cluster or send text to a model.

## Non-goals and remaining release blockers

**Do not integrate this prototype into production as proof of safety.** In particular:
- Exact command-block matching is only syntactic evidence of copying, **not** a proof that commands are safe or contextually correct.
- Prose assertions and standalone commands written as plain text are not semantically verified.
- A retrieval response is not trustworthy merely because the model reports it; the gateway must obtain or authenticate the retrieval metadata independently and bind it to the **same request** and index revision.
- Citation URLs at the document level are not source-span verification; a structured response containing source IDs, line/range evidence and precise command provenance is preferable.
- Conservative rejection currently prohibits inline code, arbitrary external links, raw HTML, reference-style links and non-shell code fences; broadening this requires a deliberately designed parser and tests.
- A public gateway must also have response limits, quotas, privacy controls, origin policy, authenticated internal service access and explicit security approval; OK-202 HIGH CVEs remain a release blocker.

The earlier A2A example contained unlinked `source_id` tokens and an invented macOS host-side Linux `virtctl` installation. Both patterns must fail validation; do not assume successful `message/send` means grounded output.
