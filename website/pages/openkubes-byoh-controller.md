---
title: "Why We Built the OpenKubes BYOH Controller"
description: "A practical engineering story about bringing existing Linux hosts into a consistent Kubernetes lifecycle—and why lifecycle safety matters as much as provisioning."
---

# Why We Built the OpenKubes BYOH Controller

*Bringing bare-metal and virtual infrastructure into a consistent Kubernetes lifecycle.*

Kubernetes infrastructure does not begin and end with cloud instances. Many teams operate physical servers, private infrastructure and virtual machines they already own. They want the benefits of Kubernetes without having to move every workload onto a single infrastructure service.

That is the environment behind our work on the OpenKubes-maintained Bring Your Own Host (BYOH) provider.

Our goal was not to build another Kubernetes distribution or replace the Cluster API ecosystem. We wanted to make existing Linux hosts first-class participants in a declarative Kubernetes lifecycle—and to be deliberate about what happens to those hosts after a cluster is created.

## Start with the infrastructure people already have

Cluster API (CAPI) gives Kubernetes operators a declarative way to manage cluster lifecycle. Its infrastructure-provider model makes it possible to connect that lifecycle to different infrastructure environments.

BYOH takes a useful approach: the Linux host is provisioned outside CAPI, then registered so that CAPI can manage its role as a Kubernetes node. That separation matters. Hardware procurement, server installation, network design and virtual-machine provisioning can remain with the infrastructure team, while Kubernetes node lifecycle is expressed through familiar Kubernetes APIs.

OpenKubes maintains a downstream fork of the BYOH provider, building on the existing work in the Kubernetes ecosystem. We preserve that foundation rather than creating a competing provisioning engine.

The result is a practical bridge between infrastructure that already exists and a consistent Kubernetes operating model.

## Provisioning is only the beginning

Creating a cluster is a visible milestone. Operating it over time is the harder, longer-lived responsibility.

Hosts need to be registered, prepared and associated with Kubernetes Machines. Versions change. Nodes need maintenance. And the meaning of an operation can differ depending on the infrastructure underneath it.

For an elastic cloud environment, replacing a machine may be a normal and useful lifecycle operation. For a dedicated bare-metal server, replacement can be a very different proposition: the hardware may be scarce, tied to a particular workload, or simply not available to recreate on demand.

That distinction led us to a broader engineering question:

**How can we make infrastructure lifecycle operations explicit, predictable and appropriate to the environment they affect?**

We treat this as a lifecycle design problem, not as a reason to abandon the Kubernetes ecosystem.

## Build on CAPI, own the lifecycle boundaries

The BYOH provider remains an implementation of the CAPI infrastructure-provider model. CAPI continues to coordinate cluster and Machine lifecycle through its APIs and controllers. The BYOH provider connects those resources to already-provisioned hosts, while host-side components participate in registration and node bootstrap.

OpenKubes focuses on the contracts around that integration: which transitions are allowed, what identity must remain stable, and what evidence is needed before an operation can be considered successful.

This is also why we distinguish an upgrade from a replacement. They may both lead to a Kubernetes node running a newer version, but they are not the same infrastructure operation.

## Making the difference between upgrade and replacement explicit

For environments where the existing host must remain the host, our proposed `InPlaceOnly` lifecycle strategy makes that expectation explicit. An in-place upgrade must preserve the identity of the existing CAPI Machine and the physical host behind it. An upgrade authorization must not silently become permission to create or delete a Machine.

For environments with suitable elastic capacity, a separate `RollingReplacement` strategy may be appropriate. In that case, replacement must have its own authorization and a demonstrably satisfied capacity and readiness contract. The fact that a provider can create another machine is not, by itself, permission to do so.

We have recorded these boundaries in two proposed platform architecture decisions:

- **ADR-Platform-047 — No-Replacement Protection and In-Place Upgrade Authorization** describes identity binding, the separation of upgrade and replacement authority, and the safety requirements for admission.
- **ADR-Platform-048 — Infrastructure Lifecycle Strategies** describes `InPlaceOnly` and `RollingReplacement`, including the different availability expectations for control planes and workers.

These ADRs are proposed decisions and an architectural direction—not a claim that every enforcement and execution component is already complete.

## Turning the principles into engineering work

The recent BYOH work brings several pieces together:

- a read-only upgrade planner that checks cluster identity, CAPI health, host inventory, package availability and workload health before an operator considers an upgrade;
- an initial No-Replacement policy and Machine admission handler, designed to fail closed for protected scope;
- regression tests and multi-architecture build coverage for the provider and its agent;
- runbooks that make the current Scaleway test baseline and the limits of earlier experiments explicit.

The distinction between planning and execution is intentional. A successful preflight is useful evidence, but it is not an upgrade. Likewise, an admission handler or a buildable Guard image is not the same thing as a fully deployed, non-bypassable production enforcement boundary.

We are keeping those maturity boundaries visible as the implementation evolves.

## One lifecycle model, different infrastructure

The longer-term direction is to support different infrastructure profiles without pretending that all infrastructure behaves alike.

Bare metal may require an in-place-first lifecycle with strong identity preservation. Cloud and OpenStack environments may support controlled rolling replacement when capacity, readiness, storage and availability requirements are satisfied. Virtual machines can provide another useful host type, while the infrastructure that creates and operates those VMs remains a separate concern.

The provider should reconcile the infrastructure contract it owns. The lifecycle strategy should constrain which transitions are acceptable. Authorization should determine whether a particular transition is permitted.

That separation keeps the architecture understandable as infrastructure choices evolve.

## What comes next

Our immediate engineering milestone is to validate a CAPI-managed, same-management-plane in-place upgrade on real Scaleway BYOH hosts. The test must show more than a new Kubernetes version: CAPI desired state and the running nodes must agree, the original Machine and host identities must remain intact, and the workflow must not fall back to replacement.

That proof has not yet been completed. We will publish the result when the implementation and evidence support it.

From there, we can extend the work to additional lifecycle strategies and test management-cluster pivoting as a separate operation.

## The bigger idea

We believe infrastructure platforms should let teams choose where Kubernetes runs without giving up a coherent way to manage it.

BYOH gives OpenKubes a foundation for connecting existing Linux hosts to CAPI. Our engineering work adds explicit lifecycle boundaries around that foundation—so that provisioning, upgrades and replacement are treated as distinct operations with clear expectations.

**Provisioning creates infrastructure. Lifecycle management makes it sustainable.**

That is why we are building on the Kubernetes ecosystem while taking ownership of the contracts that make infrastructure predictable across environments.

---

*This article describes the current engineering direction as of November 2026. The in-place upgrade executor, complete production Guard deployment and real-host Scaleway upgrade proof remain work in progress.*
