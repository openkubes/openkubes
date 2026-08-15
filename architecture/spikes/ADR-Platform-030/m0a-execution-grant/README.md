# OK-141 M0A-C1 + M0a-I execution grant

Status: **two explicit grants recorded for one bounded window**

```text
Candidate:       sha256:67e2cb5fb2484292b4a8bfc3b138209af82f672fbc8ee0269421832d5a1a271a
M0A-C1 grant:    ok141-m0a-c1-20260811-01
M0a-I grant:     ok141-m0a-i-20260811-01
Window:          2026-08-11T18:50:00Z – 2026-08-11T21:50:00Z
Maximum runs:    1
```

This record authorizes only the temporary credential lifecycle and one exact
19-object CAAPH control-plane installation on the bound `ok-mgmt` incarnation.
It does not authorize HCP/HRP submission, Cilium convergence, rollback, M0b-I,
GO-1, evidence publication, or failure injection.
