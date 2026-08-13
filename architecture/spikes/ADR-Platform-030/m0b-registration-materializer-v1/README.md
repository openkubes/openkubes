# OK-141 M0b registration materializer v1

This checkpoint implements and tests a non-authoritative runtime materializer
for the future Argo target registration. It does not contact a cluster and is
not authorized to process real credentials.

The executable accepts runtime values only through JSON on standard input,
constructs the exact reviewed AppProject and project-scoped registration
Secret in memory, and uses `kubectl create -f -` without a shell. It returns
only redacted correlation metadata and hashes of subprocess output. Raw
credential values, raw `kubectl` output, and local credential files are
forbidden.

Execution additionally requires a separate exact grant document. That guard
does not itself provide durable anti-replay state; the later bounded executor
and evidence protocol must prove that a one-run grant was consumed once.

```text
Offline tests:          9 PASS
Real credentials:       not used
Cluster contact:        none
Materializer execution: NOT GRANTED
Target registration:    NOT GRANTED
GO-1:                   NOT GRANTED
```

Run:

```bash
python3 architecture/spikes/ADR-Platform-030/m0b-registration-materializer-v1/test_materialize_registration_v1.py
python3 architecture/spikes/ADR-Platform-030/m0b-registration-materializer-v1/verify_m0b_registration_materializer_v1.py
```
