# OK-141 M0a v7.1 admission correction

Status: **OFFLINE ONLY / NO-GO**

The executor review found that the two identity entries under
`spec.validations` in the accepted v7 policy are conjunctive. Kubernetes
requires every validation to succeed, so that policy cannot express the
intended cluster-scoped OR namespaced identity choice.

v7 and its exact risk acceptance remain immutable historical evidence and are
marked not executable. v7.1 retains the reviewed 8/11 authority partition but
uses one fail-closed validation expression:

```text
exact cluster-scoped identity
OR
exact namespaced identity with a presence-guarded request.namespace
```

This checkpoint performs no cluster contact or mutation and grants no
publication or execution authority.

The corrected risk boundary was subsequently accepted as a non-authorizing
DEV decision. The resulting local execution candidate is bound to four
separate gates:

```text
M0A-AP1-v7.1  administrator prerequisite (8 objects)
M0A-C1-v7.1   temporary credential (5 RBAC/bootstrap objects)
M0A-A1-v7.1   temporary admission (policy + binding)
M0a-I-v7.1    temporary installer submission (11 objects)
```

The candidate remains `NO-GO`; its grant template has all decisions disabled.
