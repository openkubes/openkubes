# OK-141 installation-gate closure matrix

Status: **read-only analysis complete; all installation gates remain NOT GRANTED**

Baseline: `main @ f4b16b34c0d214083a343565e6fa7573d3284a75`

This checkpoint decomposes every M0a-I and M0b-I pre-installation blocker into
atomic evidence obligations. Each obligation belongs to exactly one class:

```text
OFFLINE-CLOSABLE
  deterministic analysis, immutable-source reads, rendering, verification,
  or implementation evidence that requires no target-plane mutation

LIVE-OBSERVATION
  current read-only evidence from an existing plane or service

EXPLICIT-AUTHORITY
  a named human or architecture decision bound to an exact digest and window

SEPARATE-MUTATION-GATE
  a prerequisite state change that cannot inherit authority from M0a-I,
  M0b-I, or GO-1
```

This avoids treating composite claims as one class. For example, controller
RBAC review is offline-closable, while accepting its sensitive capabilities is
an explicit authority decision. Likewise, an installer artifact can be proven
offline, but issuing its short-lived credential is a separate mutation gate.

No obligation is closed by this matrix. It only establishes the lawful path
to closure. A live observation that discovers missing state cannot create that
state; it must produce a new, separately reviewed mutation gate.

## Offline evaluation result

All nine `OFFLINE-CLOSABLE` obligations were evaluated without contacting a
Kubernetes API or authorizing a mutation:

```text
PROVEN-OFFLINE:                7
PROVEN-REPEATABLE-PREFLIGHT:   1
PARTIAL-UNRESOLVED:            1

Source blockers closed:       0
Installation gates granted:   0
```

The bounded installer prototype exposes only `materialize`, `verify`, `apply`,
and `evidence`. It validates the exact reviewed object set and target plane and
uses a fixed `kubectl` stdin transport, but every current protocol rejects
`apply` because authorization remains `NO-GO`.

The two non-final results are intentional:

- M0b-I source materialization is reproducible but must be rerun immediately
  before a final installation decision.
- CAAPH's pinned contract, dependencies, and image identity are evidenced, but
  no authoritative upstream matrix proves the exact Kubernetes v1.34.1,
  CAPI v1.13.4, and cert-manager v1.20.1 interoperability tuple.

RBAC analysis remains analysis rather than acceptance. It reports CAAPH's
cluster-scoped sensitive permissions and Argo CD's namespace-scoped Secret
permissions without granting either security boundary.

## Result

```text
Source blockers:       17/17 classified
Atomic obligations:    29
Offline-closable:       9
Live observation:       9
Explicit authority:     9
Separate mutation gate: 2

M0a-I / M0b-I:          NOT GRANTED
GO-1:                    NOT GRANTED
Infrastructure:          NO-GO
```

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/installation-closure/verify_installation_closure.py \
  --matrix architecture/spikes/ADR-Platform-030/installation-closure/installation-closure-v1.yaml \
  --digest-file architecture/spikes/ADR-Platform-030/installation-closure/installation-closure-v1.sha256

python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/installation-closure/tests \
  -p 'test_*.py' -v

python3 architecture/spikes/ADR-Platform-030/installation-closure/verify_offline_closure.py \
  --results architecture/spikes/ADR-Platform-030/installation-closure/offline-closure-results-v1.yaml \
  --digest-file architecture/spikes/ADR-Platform-030/installation-closure/offline-closure-results-v1.sha256
```
