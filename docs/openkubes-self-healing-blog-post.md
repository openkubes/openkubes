# The Immortal Platform — Building Self-Healing Digital Infrastructure with OpenKubes

*By Arash Kaffamanesh · Clouds Sky GmbH & Kubernauts GmbH*

---

There is a question that keeps every platform engineer awake at night.

Not "will my application crash?" — that is expected, and Kubernetes handles it well.

The deeper question is: **"What happens when the infrastructure that runs Kubernetes fails?"**

The server catches fire. The datacenter loses power. A misconfigured update takes down the management cluster. The network card dies at 3am on a Friday.

In most organizations, the answer is the same: someone gets paged. Someone drives to the datacenter. Someone spends hours rebuilding what was there before.

We think that answer is no longer good enough.

---

## What If the Platform Could Rebuild Itself?

Imagine a factory floor in Stuttgart. Forty autonomous mobile robots navigating around each other, guided by real-time Kubernetes workloads running on bare metal servers in a local rack.

A power surge takes down two of the three management nodes.

In most setups, this means production stops. Engineers are paged. Recovery takes hours.

In the world we are building with OpenKubes, this is what happens instead:

The bare metal controller — Metal3 — detects the failure via the server's management interface. It sends a PXE boot signal. The nodes reimage themselves from scratch. Cluster API notices the missing machines and begins provisioning replacements. ArgoCD pulls the last known good state from Git and reconciles everything back into existence.

Existing robot operations continue uninterrupted.

No human intervention. No runbook. No 3am phone call.

**The platform healed itself.**

---

## The Two Paths to Immortality

After years of running Kubernetes in production across automotive plants, financial institutions, and government agencies, we have identified two fundamentally different approaches to self-healing infrastructure — and the right answer depends on your environment.

### Path One: Metal3 and the Power of the BMC

In truly sovereign environments — air-gapped factories, military installations, industrial edge sites — cloud is not an option. The infrastructure must heal itself using only what it has.

This is where Metal3 becomes remarkable.

Metal3 is a CNCF project that treats bare metal servers the way Kubernetes treats containers. Each physical server becomes a `BareMetalHost` resource. Its power, its firmware, its boot sequence — all declared as YAML, all reconciled by a controller.

When a node fails, Metal3 does not wait for a human. It talks to the server's management interface — IPMI, Redfish, iDRAC, iLO — powers it off, wipes it, and boots a fresh operating system over the network. Cluster API then joins it back to the management cluster. ArgoCD restores every workload.

Target recovery time: under ten minutes. No humans required.

This is not science fiction. It is what the combination of Metal3, Cluster API, ArgoCD, and GitOps was built for — each layer handling one piece of the recovery, together delivering something that feels like magic.

### Path Two: The Shadow Cluster

Not every environment needs full sovereign self-healing. Some organizations run hybrid environments — bare metal on the factory floor, cloud for everything else.

For these cases, we are building something we call the **Shadow Management Cluster**.

The idea is simple. Run two management clusters simultaneously — one on-premises, one in the cloud (EKS, AKS, or GKE). Both watch the same Git repository. Both are ready to take over at any moment.

If the primary management cluster fails, the shadow takes over in seconds. Workload clusters continue running uninterrupted. When the primary recovers, it hands back control gracefully.

```
Git (Source of Truth)
       │
  ┌────┴────┐
  ▼         ▼
MGMT      MGMT Shadow
Primary   (Cloud)
  │
Workload Clusters
```

The workload clusters never know anything happened.

---

## Git Is the Source of Truth

Both approaches share one foundation: **Git**.

Everything that makes up the OpenKubes platform — the cluster definitions, the VM templates, the ingress configurations, the TLS certificates, the monitoring dashboards — is stored in a Git repository.

This is not just good hygiene. It is what makes immortality possible.

When a cluster needs to rebuild itself from scratch, it does not need a human to tell it what to do. It reads from Git. It applies. It reconciles. It heals.

The platform's desired state never changes, regardless of what the infrastructure is doing at any given moment.

> **Git is the contract. Kubernetes is the enforcer.**

This is the sentence that defines the architecture. Not just for applications — for the platform itself.

This is what true GitOps looks like — not just deploying applications from Git, but recovering entire infrastructure layers from it.

---

## The Immortality Checklist

We have defined eight criteria for a truly self-healing platform:

**RPO = 0.** Recovery Point Objective of zero means no data or configuration is ever lost. Git is always current.

**RTO < 10 minutes on-prem (target).** Early tests indicate Metal3 reprovisioning a bare metal node and rejoining the cluster in under ten minutes, end to end.

**RTO < 60 seconds cloud shadow (target).** A cloud shadow cluster taking over from a failed primary should be invisible to workload users.

**No human intervention required.** The platform heals itself. Engineers sleep through failures.

**Workload continuity.** Applications running on workload clusters should not be affected by management cluster failures.

**Full declarative state.** Every component — not just applications, but the platform itself — is declared in Git.

**Tested regularly.** Self-healing is only real if it is tested. We run chaos experiments against our own management infrastructure.

**Air-gap compatible.** For sovereign environments, the entire recovery process must work without internet access.

---

## Why This Matters Beyond Technology

The organizations we work with — automotive manufacturers, industrial automation companies, government agencies — are not just running Kubernetes because it is modern. They are running it because their most critical processes depend on it.

A car factory that cannot run its autonomous mobile robots for four hours loses millions of euros. A power grid operator that loses visibility into its distributed energy systems for thirty minutes faces regulatory consequences. A defense agency that cannot access its workload infrastructure during a network incident faces risks that cannot be quantified in money.

For these customers, **availability is not a feature. It is a requirement.**

Self-healing infrastructure is how we deliver on that requirement.

---

## Why OpenKubes?

At this point, a reasonable question is: why not Rancher? Why not Anthos? Why not OpenShift?

All of these are capable platforms. However, they typically introduce additional vendor-specific layers, operational models, or platform dependencies that organizations must adopt and maintain. When those layers change, break, or get acquired, you adapt.

OpenKubes is built differently.

Every component in OpenKubes is an upstream CNCF project — Cluster API, Crossplane, KubeVirt, Metal3, Traefik, cert-manager. There is no proprietary agent, no vendor-specific CRD, no closed-source reconciler. You own your infrastructure. You understand every layer.

This matters most in the environments where self-healing infrastructure matters most: sovereign clouds that cannot depend on external vendors, factory floors that cannot accept terms-of-service changes, government agencies that must audit every line of their stack.

OpenKubes combines Cluster API, GitOps, bare metal automation and sovereign infrastructure patterns into a unified operational model. The same five `make` commands work on bare metal, KubeVirt, EKS, AKS, and GKE.

**Open. Sovereign. Upstream-first.**

---

## Where We Are Today

OpenKubes v1.0.4 gives you a production-ready Kubernetes platform that deploys in four minutes:

```bash
make deploy         cluster=ok1   # Kubernetes cluster
make kubeconfig     cluster=ok1   # kubeconfig
make manager-deploy cluster=ok1   # Headlamp UI
make ingress-setup  cluster=ok1   # Traefik + INFRA LB
make cert-setup     cluster=ok1   # Let's Encrypt TLS
```

That is the foundation.

Self-healing infrastructure is the next chapter. We are evaluating Metal3 for bare metal node reprovisioning (OK-19), building OpenKubes Anywhere for cloud shadow clusters (OK-24), and designing the full self-healing architecture (OK-30).

---

## An Invitation

If you are building infrastructure that cannot afford to fail — factories, edge sites, sovereign clouds, critical systems — we want to hear from you.

Not to sell you something. To build something together.

The immortal platform is not a product you buy. It is an architecture you build, test, break, and improve — continuously, in the open, with a community that shares the same values.

We believe infrastructure should be treated like software, rebuilt like containers, and recovered like code. The future is not highly available infrastructure. The future is infrastructure that can disappear and come back on its own.

**Kubernetes Anywhere. Make it. Forever.**

---

🔗 [github.com/openkubes/openkubes](https://github.com/openkubes/openkubes)
📊 [OpenKubes Platform Presentation](https://kubernauts.de/en/openkubes/OpenKubes-Presentation.html)
📖 [blog.kubernauts.io](https://blog.kubernauts.io)

---

*Arash Kaffamanesh is the founder of Clouds Sky GmbH & Kubernauts GmbH and has been building and operating Kubernetes platforms for over ten years across automotive, industrial, financial, and healthcare environments.*
