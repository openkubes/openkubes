# Ingress on KubeVirt Workload Clusters

**Status:** Documented learning (OK-56) · supplements [ADR-Platform-010](../architecture/decisions/ADR-Platform-010-ingress-contract.md)
**Applies to:** Talos workload clusters provisioned as KubeVirt VMs (CAPI + CAPK)

---

## 1. Problem statement

Cilium L2 Announcements are the textbook way to expose `LoadBalancer` Services
on bare metal without BGP: the Cilium agent answers ARP requests for the
service IP on the host's physical interface.

On OpenKubes workload clusters this does not work — the announced IP is never
reachable from outside the cluster. This document explains why, on two levels,
and records the traffic path OpenKubes uses instead.

## 2. Root cause — architecture level

The workload cluster nodes are **KubeVirt VMs**, not bare-metal hosts. Their
network is a *nested* domain: VM traffic leaves through the `virt-launcher`
pod's network namespace on the infrastructure cluster.

An ARP announcement made inside that nested domain never appears on the
physical L2 segment (`enp6s0.4000`, VLAN 4000) where external clients resolve
addresses. The two L2 domains are separate; the announced LoadBalancer IP is
only ever visible inside the VM network.

## 3. Root cause — implementation level

The intuitive fix — running the Cilium agent with `hostNetwork: true` — does
not help, and understanding why is the key learning:

> Inside a KubeVirt VM, "host" means **the VM's network namespace**, not the
> bare-metal host's.

The layering:

```
Bare metal NIC (enp6s0.4000, VLAN 4000)   ← where ARP would need to happen
        │
virt-launcher pod (infra cluster)
        │
VM eth0 (10.44.x.x)                        ← what "hostNetwork" actually exposes
        │
Talos node
        │
Cilium agent (hostNetwork: true)
```

The agent sees only `eth0`. The physical NIC does not exist in its namespace,
so it can never announce the service IP on the external VLAN — regardless of
configuration. This is not a Cilium limitation or misconfiguration; it is a
structural property of nested virtualization.

## 4. Correct traffic path

External reachability terminates on the **infrastructure cluster** (the layer
that actually owns the physical network), then forwards into the VM:

```
Client
   │
MetalLB (infra cluster, ok-pool)
   │
LoadBalancer Service — selects the workload cluster's
   │                    worker virt-launcher pods
virt-launcher pod
   │
VM eth0
   │
Talos node
   │
Ingress controller (Traefik, NodePort)
   │
Application Service / Pod
```

This mirrors the pattern CAPI itself generates for the control plane
(`<cluster>-lb` Service): the same mechanism, applied to workers for ingress.

## 5. Decision

- **No Cilium L2 Announcements inside KubeVirt workload clusters.** Structurally
  impossible; do not retry with different configurations.
- **Ingress IPs are advertised by the infrastructure cluster** (MetalLB, from
  the cluster's dedicated IP block) via a `LoadBalancer` Service selecting the
  workload cluster's worker `virt-launcher` pods.
- Inside the workload cluster, the ingress contract from ADR-Platform-010
  applies unchanged: `ingressClassName: ok-ingress`, Traefik as the v1
  implementation, `<app>.<cluster>.internal` hostnames.

Redundancy and external reachability live on exactly one layer — the
infrastructure cluster. This is the same principle applied to storage
(ADR-Platform-009): the nested layer consumes the capability, it does not
re-implement it.

---

*History: this learning was produced in [OK-56](https://kubernauts.atlassian.net/browse/OK-56)
after Cilium L2 Announcements failed on ok1-talos. Reviewed three-way
(Arash / Claude / GPT) before documenting.*
