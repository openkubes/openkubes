# Open Universe Family — Complete Technology Guide

**The full OpenKubes Open Universe technology radar.**

This is a living architecture inventory, not a product catalog or guarantee of supported functionality. Each entry states its role and the nature of its current inclusion. **Internal deployment is not equivalent to general availability.**

[← Back to Open Universe](index.md)

## Implemented

### OpenKubes

**Area:** Platform Core · **Radar status:** Implemented

A Kubernetes platform framework that composes infrastructure, cluster lifecycle, Console, developer capabilities and controlled operations under explicit contracts.

### OpenTofu

**Area:** Infrastructure as Code · **Radar status:** Implemented

Declarative infrastructure provisioning. OpenKubes currently uses it and is consolidating its integration rather than creating a competing IaC engine.

### OpenSearch

**Area:** Observability · **Radar status:** Implemented

Search and analytics capability in the existing observability stack; its use is distinct from the overall OpenKubes observability contract.

### OpenCode

**Area:** AI-assisted development · **Radar status:** Implemented

Coding-agent runtime integrated into the Console Developer Workspace; not a claim of a generally available enterprise workspace.

### Open WebUI

**Area:** AI interface · **Radar status:** Implemented

Self-hosted interface for LLM workflows, already used internally by colleagues on OK AI.

### OpenClaw

**Area:** AI agents · **Radar status:** Implemented

Agent framework already used internally on OK AI; autonomous operations still require separate authorization and evidence boundaries.

## Evaluating

### OpenShell

**Area:** AI runtime security · **Radar status:** Evaluating

Candidate sandboxed runtime for bounded agents. Evaluate actual isolation, identity, egress and operational authority before adoption.

### OpenTelemetry

**Area:** Observability standards · **Radar status:** Evaluating

Vendor-neutral instrumentation, metrics, logs and traces; evaluate correlation with existing OpenSearch and operational evidence.

### Open Policy Agent (OPA)

**Area:** Governance · **Radar status:** Evaluating

Policy decisions as code. Evaluate where admission and operation authorization live, without duplicating enforcement.

### OpenCost

**Area:** FinOps · **Radar status:** Evaluating

Kubernetes cost visibility and allocation; evaluate required metrics, accuracy and tenant-level reporting.

### OpenBao

**Area:** Secrets management · **Radar status:** Evaluating

Open-source secret storage and lifecycle management; consider existing enterprise vaults and integration boundaries.

### OpenFGA

**Area:** Authorization · **Radar status:** Evaluating

Relationship-based fine-grained access control; compare against Kubernetes RBAC and OpenKubes resource ownership.

### Open Cluster Management

**Area:** Multi-cluster operations · **Radar status:** Evaluating

Potential fleet placement, add-on lifecycle and policy capabilities. OpenKubes retains cluster creation and lifecycle ownership.

### openDesk

**Area:** Collaboration apps · **Radar status:** Evaluating

Potential optional digital-workplace application; evaluate packaging, persistence, identity, upgrades and operational requirements.

### OpenProject

**Area:** Project management apps · **Radar status:** Evaluating

Potential Kubernetes-delivered project-management app; evaluate only as an optional workload rather than a platform dependency.

### OpenIAM

**Area:** Identity & access · **Radar status:** Evaluating

First identity-management candidate to evaluate for federation and enterprise lifecycle requirements. OpenKubes remains IdP-neutral.

## Planned

### OpenStack

**Area:** Infrastructure · **Radar status:** Planned

Long-term optional IaaS composition and CAPO integration; architecture references: ADR-Platform-040, OK-184, OK-106 and OK-108.

### OpenStorage

**Area:** Storage · **Radar status:** Planned

Proposed OpenKubes storage initiative built around Rook and Ceph. Fork scope, upstream synchronization and operational model remain to be decided.

## Watchlist

### OpenFeature

**Area:** Feature management · **Radar status:** Watchlist

Potential vendor-neutral feature-flag interface; monitor demand before adding another runtime dependency.

### HAMi

**Area:** GPU orchestration · **Radar status:** Watchlist

GPU sharing and scheduling technology to monitor for AI workload economics and isolation.

### Karmada

**Area:** Multi-cluster scheduling · **Radar status:** Watchlist

Alternative multi-cluster workload scheduling approach; compare with Open Cluster Management before any commitment.

### KubeVirt

**Area:** Virtual machines · **Radar status:** Watchlist

VM workloads on Kubernetes; only relevant if a validated customer workload calls for it.

### KubeStellar

**Area:** Multi-cluster workloads · **Radar status:** Watchlist

Potential multi-cluster workload distribution capabilities; monitor architecture overlap and project maturity.

## Decision and maintenance rules

A change of status needs evidence of scope, operational ownership, security, licensing, support requirements and integration tests. Optional apps remain optional. The upstream technology and the OpenKubes integration have distinct lifecycles.

**Priorities:** Stabilizing the OpenKubes CLI, cluster lifecycle and `ok up` remains more urgent than widening the technology catalog.

_Last initial editorial update: November 2026. This page is intentionally maintained through reviewed GitHub pull requests._
