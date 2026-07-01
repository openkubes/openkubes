# Kubernetes Anywhere. Make it. — How We Built OpenKubes with Crossplane and Cluster API

*By Arash Kaffamanesh · Kubernauts GmbH*

---

Most Kubernetes stories start the same way.

A team deploys their first cluster. Everything works. Then comes the second cluster. And the third. Then a request from the industrial IoT team. Then the edge deployments. Then someone asks about AWS. Suddenly, you are managing eight different tools, twelve different workflows, and nobody really knows what runs where.

We have been living this story for ten years across automotive, industrial, financial, and healthcare environments. And a few months ago, we decided to do something about it.

We built **OpenKubes**.

---

## The Problem We Were Solving

The question we kept hearing was not "can we run Kubernetes?" — everyone can run Kubernetes today.

The real question was: **"Can we run it the same way everywhere?"**

Same process for on-premises bare metal and AWS. Same day-two operations for an edge factory site and a cloud-native microservices platform. Same team, same tooling, same mental model — regardless of where the workload runs.

That is a much harder problem.

---

## What We Built

OpenKubes is not a new Kubernetes distribution. It is a **platform engineering toolkit** — a thin, opinionated layer on top of proven open-source projects that your team already knows.

At its core, OpenKubes combines three ideas:

**One:** Everything is a Kubernetes resource. Clusters, virtual machines, ingress controllers, TLS certificates — all declared as YAML, all reconciled by Crossplane. No manual steps, no imperative scripts that only the senior engineer understands.

**Two:** Everything is operated via `make`. Not because Make is glamorous, but because it is universal. Any engineer on any machine can run `make deploy cluster=ok1` without reading a 40-page runbook first.

**Three:** The platform abstracts the provider, not the operator. You still own your infrastructure. OpenKubes just makes sure you can describe it once and apply it anywhere.

---

## The Technology Behind It

We chose two CNCF projects as the foundation:

**Crossplane** acts as the platform API layer. It extends Kubernetes with custom resource definitions that represent your infrastructure as first-class objects. Want to create a virtual machine? Apply a `OpenKubesVMClaim`. Want a complete Kubernetes cluster with CNI, load balancer, and ingress? Apply a `KubeVirtClusterClaim`. Crossplane handles the rest.

**Cluster API (CAPI)** handles the Kubernetes cluster lifecycle. It models clusters, control planes, and worker nodes as Kubernetes objects — which means GitOps, drift detection, and reconciliation work out of the box.

Together they give you something remarkable: **infrastructure that heals itself**. If a node disappears, Cluster API recreates it. If a Helm release drifts from its desired state, Crossplane reconciles it. The platform is always moving toward the state you declared, not the state it happens to be in.

---

## What It Looks Like in Practice

Here is what deploying a production-ready Kubernetes cluster looks like today with OpenKubes:

```bash
make deploy         cluster=ok1   # ~2 minutes → Kubernetes cluster
make kubeconfig     cluster=ok1   # ~5 seconds  → kubeconfig saved
make manager-deploy cluster=ok1   # ~30 seconds → Headlamp UI
make ingress-setup  cluster=ok1   # ~30 seconds → Traefik ingress
make cert-setup     cluster=ok1   # ~90 seconds → Let's Encrypt TLS
```

Four minutes later, `https://headlamp.openkubes.ai` returns HTTP/2 200 with a valid TLS certificate.

No manual steps. No YAML written by hand. No undocumented tribal knowledge.

This is what platform engineering looks like when it is working.

---

## The Lessons We Learned

**Abstractions only work when they are consistent.** The moment you have two ways to do the same thing, engineers will find both of them and combine them in ways you did not anticipate. Every operation in OpenKubes goes through `make`. That constraint is a feature.

**Crossplane compositions are powerful but unforgiving.** Writing a Go-template composition that creates a KubeVirt DataVolume, Service, and VirtualMachine atomically across two clusters took longer than expected. But once it worked, it never needed to be touched again. The investment pays off over time.

**Nested virtualization has limits.** Running KubeVirt inside KubeVirt VMs (our lab setup) means MetalLB Layer 2 advertisement does not propagate to the physical network. We solved this by routing through the INFRA cluster's existing MetalLB LoadBalancer — no MetalLB on workload clusters at all. Sometimes the pragmatic solution is better than the theoretically correct one.

**Platform engineering is product engineering.** The Makefile is not just a convenience. It is the user interface of the platform. Every target is a feature. Every error message is UX copy. Every `✅` at the end of a command is a tiny moment of delight. Treat it that way.

---

## Where We Are Going

OpenKubes v1.0.4 is available today on GitHub — Community Preview, Apache 2.0.

The roadmap has three clear directions:

**OpenKubes Anywhere** — the same `make deploy` interface for EKS, AKS, and GKE. One platform API, multiple cloud providers. The user should never need to know which Cluster API provider is running underneath.

**OpenKubesMetal** — bare metal lifecycle management via Metal3. For the factory floors, industrial edge sites, and sovereign cloud environments where virtualization is not an option.

**OpenKubes Robotics** — Kubernetes for autonomous systems. Open-RMF, ROS2, fleet orchestration, and industrial AI — all managed through the same platform model.

The vision is simple:

> **Deploy a complete robot factory site from Git.**

We are not there yet. But we know exactly where we are going.

---

## Try It

OpenKubes is open source and available today:

🔗 [github.com/openkubes/openkubes](https://github.com/openkubes/openkubes)

📊 [OpenKubes Platform Presentation](https://kubernauts.de/en/openkubes/OpenKubes-Presentation.html)

If you are running Kubernetes in production — especially across mixed environments — we would love to hear from you.

*Platform Engineering. Sovereign Infrastructure. Kubernetes Anywhere.*

---

*Arash Kaffamanesh is the founder of Kubernauts GmbH and has been building and operating Kubernetes platforms for over ten years across automotive, industrial, financial, and healthcare environments.*
