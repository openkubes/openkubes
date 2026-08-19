# research/ — uncontracted work

What lives here: investigations, PoCs and lab assets that are **not** part of the
OpenKubes platform contract. Nothing under `research/` is governed by an ADR,
nothing here is a dependency of a platform component, and nothing here commits
OpenKubes to a tool, a vendor or an interface.

Why the separation is a directory and not a disclaimer: placement in `platform/`
carries architectural meaning. A reader — or a future maintainer, or a customer
reviewing the repository — reasonably treats `platform/**` as the contracted
platform. A README paragraph saying "this is only an experiment" does not cancel
that signal, so uncontracted work is kept out of the tree instead of annotated
inside it.

| Path | What it is |
|---|---|
| [`requirements-inventory.md`](requirements-inventory.md) | requirements collection, pre-ADR |
| [`kagent-standalone/`](kagent-standalone/README.md) | OK-129 standalone kagent operations PoC — lab manifests and the access-profile renderer |

## Promoting something out of here

Moving an asset into `platform/` is an adoption decision, not a file move. It
needs, at minimum:

1. an ADR that records the decision and its alternatives;
2. a named consumer that actually depends on it;
3. a contract or interface the rest of the platform can rely on;
4. the evidence that the claims it makes hold — for anything security-relevant,
   verified against a live cluster rather than argued from the manifests.

Until then the work stays here, where it can be evaluated honestly.
