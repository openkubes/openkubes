# OpenKubes Referenzarchitektur v1

## 1. Architekturidee in kompakter Form

```txt
OpenKubes trennt die Plattform bewusst in drei Ebenen:

Management-Ebene:
Steuert, provisioniert, überwacht und schützt die Plattform.

Infrastruktur-Ebene:
Stellt die physischen und virtualisierten Ressourcen bereit.

Tenant-/Workload-Ebene:
Hier laufen die eigentlichen Kundensysteme, Plattformdienste und Spezial-Workloads.

Die Leitidee ist:

Kubernetes als Control Plane
KubeVirt als VM-Layer
Cluster API als Cluster-Lifecycle-Layer
Crossplane als Plattform-API und Service-Kompositions-Layer
```

## 2. ASCII-Gesamtbild

```txt
┌──────────────────────────────────────────────────────────────────────────────┐
│                            OpenKubes Referenzarchitektur v1                  │
└──────────────────────────────────────────────────────────────────────────────┘

                                NORTHBOUND
     ┌────────────────────────────────────────────────────────────────────┐
     │ Self Service Portal / API / GitOps / CI-CD / Service Catalog       │
     │ Developer • Platform Team • Ops • Tenant Admins                    │
     └────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  MANAGEMENT ZONE                                                             │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │ OpenKubes Management Cluster                                           │  │
│  │                                                                        │  │
│  │  - Crossplane                                                          │  │
│  │  - Cluster API                                                         │  │
│  │  - GitOps Controller (Flux)                                            │  │
│  │  - Policy Engine / Admission / Governance                              │  │
│  │  - Secrets / External Secrets                                          │  │
│  │  - Platform Operators                                                  │  │
│  │  - Central Observability Control                                       │  │
│  │  - Inventory / Automation / Day-2 Controllers                          │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  APIs / Products:                                                            │
│  - OpenKubesCluster                                                          │
│  - OpenKubesVM                                                               │
│  - OpenKubesDatabase                                                         │
│  - OpenKubesAIWorkspace                                                      │
│  - OpenKubesCADPool                                                          │
│  - OpenKubesTenant                                                           │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  INFRASTRUCTURE ZONE                                                         │
│                                                                              │
│  ┌───────────────────────────┐  ┌───────────────────────────┐                │
│  │ Bare Metal Compute        │  │ Bare Metal GPU Nodes      │                │
│  │ General / Control / VM    │  │ AI / CAD / VDI / HPC      │                │
│  └───────────────────────────┘  └───────────────────────────┘                │
│                                                                              │
│  ┌───────────────────────────┐  ┌───────────────────────────┐                │
│  │ Storage Domain            │  │ Network Domain            │                │
│  │ Block / File / Object     │  │ CNI / LB / BGP / VLAN     │                │
│  │ Snapshots / Backup        │  │ Multus / Segmentation     │                │
│  └───────────────────────────┘  └───────────────────────────┘                │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │ Virtualization & Cluster Runtime                                       │  │
│  │                                                                        │  │
│  │  - Kubernetes Infra Cluster(s)                                         │  │
│  │  - KubeVirt                                                            │  │
│  │  - VM templates / golden images                                        │  │
│  │  - GPU pass-through / mediated devices                                 │  │
│  │  - Cluster API providers                                               │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  TENANT / WORKLOAD ZONE                                                      │
│                                                                              │
│  ┌────────────────────────────┐  ┌────────────────────────────┐              │
│  │ Tenant K8s Cluster A       │  │ Tenant K8s Cluster B       │              │
│  │ App / APIs / Services      │  │ Regulated / Dedicated      │              │
│  └────────────────────────────┘  └────────────────────────────┘              │
│                                                                              │
│  ┌────────────────────────────┐  ┌────────────────────────────┐              │
│  │ VM Pools                   │  │ Platform Services          │              │
│  │ Windows / Legacy / CAD     │  │ DBaaS / MQ / AI / Search   │              │
│  └────────────────────────────┘  └────────────────────────────┘              │
│                                                                              │
│  ┌────────────────────────────┐  ┌────────────────────────────┐              │
│  │ AI / GPU Workloads         │  │ MPI / HPC Workloads        │              │
│  │ Training / Inference       │  │ Batch / Parallel Jobs      │              │
│  └────────────────────────────┘  └────────────────────────────┘              │
└──────────────────────────────────────────────────────────────────────────────┘

                                CROSS-CUTTING DOMAINS
┌──────────────────────────────────────────────────────────────────────────────┐
│ Identity • RBAC • OIDC • Network Policies • Security • Compliance            │
│ Observability • Logging • Tracing • Backup • DR • Cost/Capacity              │
│ Patch / Upgrade • Policy-as-Code • Audit • Image Governance                  │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 3. Schichtenbild

```txt
Schicht A — Consumer / Access Layer

Das ist der Eingangspunkt für Nutzer und Teams.

Typische Zugänge
Self-Service-Portal
GitOps Repositories
API
CI/CD
Servicekatalog
Ticket-/Freigabeintegration für regulierte Umgebungen

Zweck

Teams sollen nicht direkt “Infra zusammenschrauben”, sondern definierte Produkte konsumieren:

Cluster
VM
Datenbank
GPU-Workspace
CAD-Pool
Projekt-Landing-Zone
Schicht B — Platform Control Layer

Das ist der wichtigste Kern von OpenKubes.

Verantwortlichkeiten
Produktobjekte annehmen
Ressourcen komponieren
Policies durchsetzen
Lebenszyklen steuern
Drift erkennen
Day-2-Aktionen auslösen
Kernelemente
Crossplane
Cluster API
GitOps
Plattformoperatoren
Admission / Policy
Secret-Integration
Tenant- und Klassenlogik

Diese Schicht ist die eigentliche OpenKubes-Plattformintelligenz.

Schicht C — Resource Orchestration Layer

Hier wird aus Plattformlogik reale Infrastruktur.

Verantwortlichkeiten
VMs anlegen
Kubernetes-Cluster erzeugen
Netzprofile zuweisen
Storage anbinden
GPU-Ressourcen zuweisen
Workload-Klassen platzieren
Kernelemente
KubeVirt
Cluster API
Node Pools
Storage Classes
Multus / Netzprofile
VM Templates
Images
Schicht D — Runtime Layer

Hier laufen die eigentlichen Nutzlasten.

Enthält
Shared und Dedicated Kubernetes Cluster
virtuelle Maschinen
GPU-Workloads
Datenbanken
CAD-Desktops / CAD-Pools
Batch-/MPI-Jobs
Middleware
Schicht E — Operations & Governance Layer

Diese Schicht sorgt dafür, dass die Plattform langfristig tragfähig bleibt.

Umfasst
Monitoring
Logging
Tracing
Alerting
Backup
Restore
DR
Compliance
Patching
Vulnerability Management
Kapazitätsplanung
SLO/SLA-Management
```

## 4. Kernflüsse der Architektur

```txt
A. Cluster-as-a-Service
User / Team
   │
   ▼
OpenKubesCluster CR
   │
   ▼
Crossplane Composition
   │
   ▼
Cluster API resources
   │
   ▼
KubeVirt / Infra provider resources
   │
   ▼
Tenant Cluster wird erstellt
   │
   ▼
GitOps bootstrap + Addons + Policies + Observability
Ergebnis

Ein Team bekommt keinen “wilden Cluster”, sondern einen standardisierten, gehärteten, beobachtbaren Cluster.

B. VM-as-a-Service
User / Team
   │
   ▼
OpenKubesVM CR
   │
   ▼
Crossplane / VM blueprint
   │
   ▼
KubeVirt VM + Netzprofil + Storage + Policy
   │
   ▼
Golden Image + Bootstrap + Backup Policy

Ergebnis

VMs werden wie Plattformprodukte behandelt, nicht wie manuell gepflegte Einzelobjekte.

C. DBaaS
User / Team
   │
   ▼
OpenKubesDatabase CR
   │
   ▼
Crossplane Composition / DB Operator / Helm Release
   │
   ▼
DB Instanz + Storage + Backup + Monitoring + Secret
Ergebnis

Datenbanken entstehen standardisiert, versionierbar und mit Day-2-Bausteinen.

D. GPU / AI
AI Team
   │
   ▼
OpenKubesAIWorkspace / GPU class
   │
   ▼
Placement auf GPU Node Pool
   │
   ▼
GPU device plugin + storage + quotas + observability
   │
   ▼
Notebook / Training / Inference Runtime
Ergebnis

GPU ist keine Sonderlocke, sondern definierte Plattformdomäne.

E. CAD Pools / virtuelle Engineering-Workloads
Engineering Team
   │
   ▼
OpenKubesCADPool
   │
   ▼
VM Pool Blueprint
   │
   ▼
GPU-enabled VMs + Netzsegment + Profile + Image + Lizenzanbindung
   │
   ▼
skalierbarer CAD/VDI Pool
```

## 5. Platzierung der Hauptthemen in der Architektur

```txt
AI / GPU Workloads
Empfohlene Platzierung
dedizierte GPU Worker in der Infrastruktur-Ebene
Nutzung entweder in Tenant-Clustern oder spezialisierten Shared AI-Zonen
harte Trennung zwischen:
Training
Inference
Interactive
GPU-VMs für CAD/VDI
Wichtige Architekturregeln
GPU niemals als “globale Shared Ressource ohne Governance”
Quotas und Klassen zwingend
GPU-Monitoring und Kapazitätsplanung Pflicht
unterschiedliche SLAs für AI und CAD
MPI / HPC
Empfohlene Platzierung
als spezialisierte Workload-Zone
möglichst nah an dedizierten Node Pools
mit reduziertem Plattform-Overhead
Multus / spezialisierte Netzpfade wenn erforderlich
Wichtig

HPC darf nicht durch generische Enterprise-Plattformmechanik unnötig gebremst werden.
OpenKubes sollte HPC unterstützen, aber nicht jede HPC-Domäne komplett überfrachten.

DBaaS
Empfohlene Platzierung
logisch als Plattformservice
physisch entweder:
in dedizierten Stateful-Zonen
oder je Klasse in Tenant-/Service-Clustern
Architekturregeln
nicht alles Shared
Storage- und Backup-Klassen klar definieren
Recovery regelmäßig testen
DBaaS als Produktlinien aufbauen:
bronze
silver
gold
CAD Pools
Empfohlene Platzierung
KubeVirt-basierte VM-Pools
dedizierte GPU-/VDI-Nodes
separate Netzwerksegmente
Image- und Profil-Management
optional eigener Tenant-/Projektbereich
Warum VM-basiert?

Viele CAD-/Engineering-Workloads brauchen:

GPU
Windows
feste Images
Lizenzintegration
kontrollierte Benutzerumgebungen

Das ist ein idealer Anwendungsfall für KubeVirt-basierte VM-Pools.
```

## 6. Empfohlener Komponenten-Stack

Ich formuliere das bewusst als empfohlene OpenKubes-Standardlinie.

```txt
6.1 Plattformkern
Management Cluster
Kubernetes: RKE2 oder Talos
GitOps: Flux
Plattform-API: Crossplane
Cluster Lifecycle: Cluster API
VM Layer: KubeVirt
Secret Integration: External Secrets
Zertifikate: cert-manager
Policy: Kyverno oder OPA/Gatekeeper
Identity: Keycloak oder bestehender Enterprise IdP via OIDC

6.2 Netzwerk
Standardlinie
CNI: Cilium als moderne Default-Empfehlung
Alternative: Calico bei starker BGP-/Bestandsorientierung
Spezialnetze: Multus
Load Balancer: MetalLB oder BGP-basierte LB-Integration
North-South: Ingress / API Gateway getrennt denken
Netzwerkzonen
Management
Storage
Pod/Service
VM Tenant
External
Spezialnetze für GPU/HPC

6.3 Storage
Minimal
Longhorn oder externes Blockstorage
S3-kompatibler Object Storage
einfache Snapshot-/Backup-Fähigkeit
Enterprise
Rook/Ceph
Block + File + Object aus einer Domäne
Snapshots / Clones / Replikation
DR-fähige Klassen
Ergänzung

Für CAD, AI und Daten-Sharing braucht man fast immer zusätzlich:

Shared File Storage
Object Storage
schnelle Scratch-/Workspaces

6.4 Observability
Basis
Metrics Stack
Logging Stack
Tracing optional
Alerting
Audit Logs
OpenKubes-Empfehlung

Trennung von:

Plattform-Observability
Tenant-Observability
Security-/Audit-Daten

6.5 Backup / DR
Basis
Kubernetes-Backup
PV-/Snapshot-Backup
VM-Backup
DB-spezifische Backups
objektbasierte Backup-Ziele
Ziel

Wiederherstellung muss für diese Ebenen definiert sein:

einzelnes Objekt
Namespace / DB
VM
Cluster
Site
6.6 Security / Compliance
Standardkomponenten
OIDC / SSO
RBAC
Namespaces / Tenants
Network Policies
Admission Policies
Image Scanning
Secret Management
Runtime Security
Audit / Compliance Reporting
```

## 7. OpenKubes Schichten als Produktmodell

```txt
Ein starker Teil der Zielarchitektur ist, dass sie nicht nur technisch, sondern auch produktförmig ist.

Produktklasse 1 — Foundation
Bare Metal Capacity
Netzwerk
Storage
Plattformkern
Produktklasse 2 — Runtime
Kubernetes Cluster
VMs
Tenant Zones
Produktklasse 3 — Platform Services
DBaaS
Messaging
Observability
Search
Object Storage Access
Produktklasse 4 — Specialized Services
AI Workspaces
GPU Pools
CAD Pools
HPC Pools
Produktklasse 5 — Governance Services
Compliance Profiles
Backup Policies
Security Baselines
Tenant Guardrails
```

## 8. Minimal-Referenzarchitektur

```txt
Ziel

Schnell umsetzbar, aber mit sauberer Richtung.

[1] Management Cluster
    - RKE2
    - Flux
    - Crossplane
    - Cluster API
    - KubeVirt control integration
    - cert-manager
    - External Secrets
    - Keycloak/OIDC
    - Basis Monitoring

[2] Infra/Runtime Cluster oder kleine Clustergruppe
    - KubeVirt
    - CNI
    - Load Balancer
    - Storage
    - VM templates
    - erste GPU Nodes optional

[3] Standardprodukte
    - OpenKubesCluster
    - OpenKubesVM
    - OpenKubesDatabase (Postgres zuerst)
    - OpenKubesTenant

[4] Day-2 Basis
    - Backup
    - Monitoring
    - Logging
    - Patchfenster
    - dokumentierte Runbooks
Wann ist das gut genug?

Wenn du damit reproduzierbar erzeugen kannst:

einen Tenant-Cluster
eine Standard-VM
eine kleine DB
ein isoliertes Tenant-Projekt
grundlegendes Monitoring und Backup
```

## 9. Enterprise-Referenzarchitektur

```
Ziel

Mehrere Plattformdomänen, höhere Isolierung, Spezialisierung und Betriebsreife.

[1] Dedizierte Management Zone
    - getrennt und gehärtet
    - hochverfügbar
    - klare Zugriffsdomänen

[2] Separate Infra Zone
    - dedizierte Compute-, GPU-, Storage- und Spezialnode-Pools
    - Netzwerksegmentierung
    - Rack-/Failure-Domain-Awareness

[3] Tenant Zone
    - Shared und Dedicated Cluster
    - VM-Pools
    - isolierte Projekt-Landing-Zones

[4] Service Zone
    - DBaaS
    - Messaging
    - Search
    - Observability Backends
    - AI artifacts / model storage

[5] Specialty Zone
    - AI/GPU
    - CAD/VDI
    - HPC/MPI

[6] Governance & DR
    - Compliance Profile
    - zweite Site / Recovery
    - getestete Restore-Pfade
    - Kapazitäts- und Kostensteuerung
```

## 10. OpenKubes Architekturentscheidungen
```txt
Entscheidung 1

Crossplane ist Produkt- und API-Layer, nicht Ersatz für jede tiefere Runtime-Mechanik.

Entscheidung 2

Cluster API bleibt der Standardweg für Kubernetes-Cluster-Lifecycle.

Entscheidung 3

KubeVirt ist die strategische VM-Laufzeit für VM-Workloads innerhalb der Plattform.

Entscheidung 4

Storage ist mehrklassig und nicht monolithisch.

Entscheidung 5

GPU, CAD und HPC bekommen eigene Ressourcenklassen und Betriebsregeln.

Entscheidung 6

Management-Ebene bleibt klein, stabil und gehärtet.

Entscheidung 7

Tenant-Isolation wird gestuft umgesetzt: Namespace, Cluster oder dedizierte Zone.

Entscheidung 8

Immutable Nodes & OS
Die Infrastruktur-Ebene setzt auf ein minimales, (wenn möglich) immutables Betriebssystem (wie Talos oder ein gehärtetes RHEL/SLES CoreOS-Derivat). Updates erfolgen durch Node-Replacement, nicht durch In-Place-Patching.

## 11. Empfohlene erste OpenKubes APIs

Für die Umsetzung würde ich diese Objekte als erste Produkt-APIs priorisieren:

Sinnvolle Reihenfolge

OpenKubesTenant
OpenKubesCluster
OpenKubesVM
OpenKubesDatabase
OpenKubesBackupPolicy
OpenKubesGPUWorkspace
OpenKubesCADPool
```

## 12. Was diese Referenzarchitektur bewusst nicht tut

```txt
Sie vermeidet absichtlich einige typische Fehler:

kein “alles in einen einzigen Cluster”
kein Vermischen von Management und produktiven Spezialworkloads
kein blindes Kopieren klassischer Virtualisierungsarchitekturen
kein Überfrachten von Crossplane mit Low-Level-Betriebsdetails
kein GPU-Sharing ohne Governance
kein Storage als nachträgliches Nebenthema
kein Self Service ohne Guardrails

## 13. Mein konkretes Architektur-Fazit für OpenKubes

Die stärkste OpenKubes-Zielarchitektur ist aus meiner Sicht:

ein kleiner, sauber gehärteter Management-Cluster
eine oder mehrere Infrastruktur-/Runtime-Zonen
Crossplane als OpenKubes-Produkt-API
Cluster API für Cluster-Lifecycle
KubeVirt für VMs und spezialisierte VM-Pools
klare Spezialisierung für GPU, CAD, DBaaS und HPC
starke Day-2- und Governance-Schicht von Anfang an

So entsteht keine “Technikdemo”, sondern eine plattformfähige On-Prem-Zielarchitektur.
```