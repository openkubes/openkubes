# OK-141 Happy Run resume v4

Resume v3 correctly bound a post-G3 start point, but its inherited historical
validator still enforced the after-G1 safety rule that G3 evidence must be
absent. That rule prevented any cluster contact, so the v3 grant remained
unconsumed.

This additive v4 candidate narrows the validator transition:

```text
after-G1 resume
  -> G3 evidence must be absent

post-G3 resume
  -> the exact bound G3 evidence must be present
```

The preflight, G1 operation set, remediation, lifecycle, G3 and failed
NetworkReady evidence are still validated by exact private paths and digests.
The wrapper bypasses only the historical absence check. It does not execute
Lifecycle or G3 and does not add generic retry, rollback or cleanup behavior.

This checkpoint remains `NO-GO`; the unconsumed v3 grant is not reusable.

Offline verification:

```bash
python3 architecture/spikes/ADR-Platform-030/go1-happy-run-resume-v4/test_happy_run_resume_v4.py
python3 architecture/spikes/ADR-Platform-030/go1-happy-run-resume-v4/bounded_happy_run_resume_v4.py verify
```
