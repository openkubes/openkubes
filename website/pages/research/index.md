# OpenKubes Research

**Open questions. Explicit assumptions. Independently verifiable evidence.**

Research is where OpenKubes investigates security architecture, Kubernetes lifecycle behavior, and experimental approaches **before** they become accepted architecture decisions or production capabilities.

Research findings do not automatically change an ADR, approve an implementation, or certify a deployment.

## Research areas

<figure class="ok-research-diagram ok-research-diagram--preview">
  <a href="/research/security/hitl-hotl-policy-bounded-autonomy/" aria-label="Read Research Paper 001: Policy-Bounded Autonomy">
    <img src="/research/security/policy-bounded-autonomy.svg" alt="Illustrated overview of Human Governance, Trusted Policy Authority, Kubernetes reconciliation, and independent evidence." loading="lazy">
  </a>
  <figcaption>Research Paper 001 — a reviewed architecture hypothesis, not deployed HOTL functionality. <a href="/research/security/hitl-hotl-policy-bounded-autonomy/">Read the paper overview</a>.</figcaption>
</figure>

### [Security & Trust](security/index.md)

Human oversight, operational authority, least privilege, revocation, recovery, and policy-bounded autonomy.

### [Experiments & Evidence](experiments/index.md)

Reproducible validation, negative tests, and clearly scoped evidence. Experiments only support claims about their tested versions, profiles, and conditions.

## How to read research status

| Status | Meaning |
| --- | --- |
| Research Draft | Investigation and proposed design; no independent validation implied |
| Reviewed Research | Independent feedback has been recorded; open findings remain visible |
| Experimental Validation | Specific mechanisms are being tested; individual results must state PASS, FAIL, or NOT PROVEN |
| Architecture Decision | Normative decisions live separately in the [ADR repository](https://github.com/openkubes/openkubes/tree/main/architecture/decisions), with their own acceptance status |

These labels describe **documents and evidence**, not a progression toward autonomous infrastructure control.

For established principles, see [Security First](/architecture/security-first/). For implementation stories and announcements, see the [Blog](/blog/).
