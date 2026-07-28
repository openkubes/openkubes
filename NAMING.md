# OpenKubes — Naming & Terminology

Canonical naming decision for the OpenKubes project. This is the single source of
truth for how we name the framework, the reference distribution, and everything
around it — in docs, README, website, code, and conversation.

## Canonical definition

> **OpenKubes is the framework for building sovereign Kubernetes platform
> distributions. OpenKubes Platform (OKP) is its official reference distribution
> and conforms to the OpenKubes contracts.**

Mnemonic:

> **OpenKubes defines the framework. OKP proves it can run.**

## Terminology

| Term | Meaning / Usage |
| --- | --- |
| **OpenKubes** | The framework: contracts, architecture, principles, methodology, conformance rules. Also the overall project/brand. |
| **OpenKubes Platform (OKP)** | The official, runnable **reference distribution** of OpenKubes. Maintained by the project. |
| **OK** | Informal short name for OKP. Internal/spoken use only, never the official product name. |
| **Composition** | A concrete technical assembly of the `ok-*` building blocks (`ok-mgmt`, `ok-shared`, `ok-ai`, `ok-robotics`, …). |
| **Custom distribution** | A third-party distribution built on OpenKubes. Not a variant of OKP. |
| **OpenKubes-conformant** | Satisfies the relevant OpenKubes contracts and conformance rules. Conformance is **always relative to a version and a profile / applicability declaration** — never a blanket yes/no (see below). |
| **OKF** (reserved) | *OpenKubes Framework* — reserved name, **not currently active**. See activation rule below. |
| **OKX** | Not a name. Insider joke only (collides with the OKX crypto exchange). |

## The `ok-*` building blocks

The reference distribution OKP is composed of:

- `ok-mgmt` — management capabilities
- `ok-shared` — shared services
- `ok-ai` — AI capabilities
- `ok-robotics` — robotics capabilities

These are the concrete capabilities/components of the OKP composition.

## Relation wording

Use the right verb for the right context. The primary relation is **conformance**.

- **built with OpenKubes** — approachable, outward-facing framing.
- **conforms to the OpenKubes contracts** — precise technical statement (preferred).
- **reference distribution** — the *only* role word to use externally. Be consistent.
- Avoid: *instance of* (OKP is not an object instantiated from the framework).
- Avoid where possible: *implementation of the framework* — too narrow. A distribution
  can satisfy contracts through different components and providers rather than
  implementing every framework artifact directly.

### The one-liner for outward messaging

> Deploy OKP as provided, adapt it, or use OpenKubes to build your own
> sovereign Kubernetes platform distribution.

> **Note:** Only the official reference distribution is called **OKP**. Custom
> distributions are *built on OpenKubes* / *OpenKubes-conformant* — they are **not**
> "your own OKP".

## Rule: one external role word

Externally, always say **"reference distribution."** Do not mix in "reference
implementation" or "reference composition" as the public role word.

- *reference implementation* — acceptable only inside deep technical explanations,
  never as the primary role word.
- *composition* — reserved for the concrete internal assembly of `ok-*` blocks.

## Conformance is scoped, not binary

A distribution is never simply "OpenKubes-conformant." Conformance must always name:

- **a version** — which OpenKubes contract version it was validated against, and
- **a profile / applicability declaration** — which set of contracts apply, since not
  every distribution must satisfy every contract (e.g. an edge distro may not claim
  the robotics contracts).

Correct: `Distribution A is OpenKubes-conformant against contracts 1.0, profile: datacenter.`
Not: `Distribution A is OpenKubes-conformant.`

## Activation rule for OKF

> The name **OpenKubes Framework (OKF)** remains **reserved**. It may be introduced
> only when the framework becomes an **independently versioned and consumable
> deliverable with its own lifecycle** and **multiple conforming distributions**.

Names follow artifacts, not diagrams. A repository alone is not enough — OKF earns
its name only when it has an independent lifecycle. Concretely, OKF is justified once
statements like these become meaningful and verifiable:

```text
OKP 1.2 conforms to OpenKubes Framework 1.0.
Customer Distribution A was validated against OKF 1.0.
OKF 1.1 changes the platform contracts without requiring an OKP release.
```

That requires the framework to have, independently of OKP:

- versioned contracts / schemas
- a conformance suite
- policies and validation rules
- a defined release version
- documented compatibility boundaries
- consumers other than OKP

Until then, **OpenKubes** is the more precise and stronger name for the framework.

### Target taxonomy once OKF is active

```text
OpenKubes Framework 1.x
        ├── OKP 1.x  (official reference distribution)
        ├── Customer Distribution A
        └── Edge Distribution B
```

### Future OKP editions (when needed)

Prefer editions under the OKP name over introducing new brands:

- OpenKubes Platform — Datacenter Edition
- OpenKubes Platform — Edge Edition
- OpenKubes Platform — Robotics Edition

## Summary

- **OpenKubes** = framework (and project/brand).
- **OKP** = official reference distribution; **OK** informal.
- **conforms to the OpenKubes contracts** = the defining relation.
- **"reference distribution"** = the only external role word.
- **OKF** = reserved, activated only by an independent lifecycle + multiple conforming distributions.
- **OKX** = joke, not a name.
