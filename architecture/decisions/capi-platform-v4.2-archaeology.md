# OpenKubes Archaeology — Mapping Matrix

**Methode (GPT):** Für jede Zeile: (1) Welches Problem wurde gelöst? (2) Existiert das Problem heute noch? (3) Welchen Vertrag implementiert es?

---

## ok-cluster vs. capi-platform-v4.2 — direkter Vergleich

| Aspekt | capi-platform-v4.2 | ok-cluster |
|---|---|---|
| **Eingabe** | Crossplane Claim (`KubeVirtClusterClaim`) | `cluster-config.yaml` (lokale Datei) |
| **Trigger** | Composition → Kubernetes Job → Runner-Container | `make render` / `make install` (lokal, CLI) |
| **Templating** | `envsubst` über `.tpl` Dateien, ENV-Variablen aus ConfigMap | Python `render.py`, `string.Template`, liest YAML direkt |
| **IP/CIDR Allokation** | Manuell im Claim (`endpointIP` Pflichtfeld) | Automatisch (`auto` → next-free aus Pool) |
| **Provider-Abstraktion** | `spec.provider: kubevirt` Feld existiert in XRD (nur 1 Provider implementiert) | `type: talos\|ubuntu` (kein expliziter Infra-Provider-Begriff) |
| **OS-Vertrag** | Talos Version + Schematic ID hart in `.env`/Templates | `os.schematic_id` in `cluster-config.yaml`, liest aus ok-linux Konzept |
| **Lifecycle Targets** | deploy, recreate, upgrade, delete, status, logs, check, force-clean, manager-*, ingress-*, cert-* | new, render, install, bootstrap, upgrade, clean, teardown, list, status |
| **Self-Service** | Ja — Crossplane Claim ist eine K8s-API, RBAC-fähig, GitOps-tauglich | Nein — CLI/Makefile, lokal ausgeführt |
| **Ausführungsort** | In-Cluster (Job läuft im Management Cluster) | Lokal auf dem Rechner des Operators |
| **Upgrade-Strategie** | Rolling + Recreate, beide implementiert und getestet | Blue-green geplant, "experimental" Status |
| **Ingress/TLS/Manager** | Vollständig: Traefik, cert-manager, Headlamp — alles via `make` | Nicht vorhanden |
| **Reife** | Production-proven laut README (50+ Cluster), v1.0.4 | Frisch gebaut, 1 funktionierender Cluster (ok1-talos) |

### GPTs drei Fragen angewendet

**1. Welches Problem wollte capi-platform-v4.2 lösen?**
Self-Service Cluster-Provisionierung über eine deklarative Kubernetes-API (Crossplane Claim), sodass ein Cluster durch `kubectl apply` oder GitOps entsteht — nicht durch einen Menschen der ein CLI-Tool bedient.

**2. Existiert dieses Problem heute noch?**
Ja — uneingeschränkt. Das ist sogar das Problem das GPT gestern als "Platform CRD" vorausgesagt hat (`os.profile`, `cluster.profile`, etc.). Es existiert nicht nur noch, es ist die Zielarchitektur.

**3. Welchen Vertrag implementiert es?**
Den **Cluster Lifecycle Contract über eine deklarative API** — Claim rein, Cluster raus. `ok-cluster` implementiert denselben Vertrag, aber über eine CLI/Makefile statt über eine Kubernetes-API.

**Vorläufige Erkenntnis:** Das ist keine Konkurrenz von zwei Implementierungen desselben Produkts. Es sind zwei verschiedene Interfaces für denselben Contract:

```
Cluster Lifecycle Contract
        │
        ├── CLI/Makefile interface   →  ok-cluster (lokal, Operator-getrieben)
        └── Kubernetes API interface →  capi-platform-v4.2 (Self-Service, GitOps-fähig)
```

Das wirft die eigentliche Frage auf: Ist `ok-cluster` eine **Implementierung** des Cluster-Lifecycle-Contracts (so wie capi-platform-v4.2 eine ist) — oder ist `ok-cluster` der **Contract selbst**, den capi-platform-v4.2 als eine von mehreren möglichen API-Oberflächen exponiert?

---

## Component-Mapping (GPT-Vorschlag, verifiziert)

| Component | Current Location | Current Responsibility | Problem (still exists?) | Likely Future Owner | Action |
|---|---|---|---|---|---|
| `xrd.yaml` (KubeVirtClusterClaim) | openkubes/platform/cluster-management/crossplane | Definiert Self-Service API für Cluster-Erstellung | Ja — das ist exakt der "Platform CRD" Gedanke von gestern | openkubes/openkubes (Plattform-Vertrag) | **keep + formalize as contract** |
| `composition.yaml` | openkubes/platform/cluster-management/crossplane | Übersetzt Claim → ConfigMap + Job | Ja, aber die Implementierung (Job + Runner-Container) könnte durch ok-cluster ersetzt werden | openkubes/openkubes (Integrationsschicht) | **keep, refactor target** |
| `capi-platform-v4.2` Runner (Templates, render.sh) | openkubes/platform/cluster-management/capi-platform-v4.2 | Rendert CAPI/CAPK Manifeste via envsubst, wendet sie an | Ja — identisch zum Problem das `ok-cluster render.py` löst | ok-cluster (Implementierung) | **migrate / consolidate mit ok-cluster** |
| `config/providers/kubevirt.env` | capi-platform-v4.2/config | Provider-spezifische Defaults | Ja — das ist der `infrastructure.provider` Layer von gestern, real existierend | ok-cluster oder neuer ok-infra Provider-Layer | **extract as explicit contract** |
| Lifecycle Make-Targets (deploy/recreate/upgrade/status/delete) | capi-platform-v4.2/Makefile | Cluster Lifecycle Operationen | Ja | ok-cluster (bereits teilweise vorhanden, aber ohne Ingress/TLS/Manager) | **migrate fehlende Targets (ingress, cert, manager) nach ok-cluster** |
| Headlamp Integration (manager-*) | capi-platform-v4.2/Makefile | Cluster-Manager-UI Deployment | Ja | ok-apps (Applications Layer) | **migrate später** |
| Ingress/TLS (Traefik, cert-manager) | capi-platform-v4.2/Makefile | Ingress + Zertifikate für Workload-Cluster | Ja | ok-apps oder ok-gitops | **migrate später** |
| `runner/Dockerfile`, `entrypoint.sh` | capi-platform-v4.2/runner | Container-Image für In-Cluster-Ausführung | Ja, falls Self-Service-API-Pfad beibehalten wird | ok-cluster (als optionales "Runner Mode") oder ok-local | **decide: braucht ok-cluster einen In-Cluster-Modus?** |
| ADR-001 (Hosted Control Plane) | architecture/decisions | Pod-basierte Control Planes für Dev/Test, Kamaji bewusst abgelehnt | Ja — vollständig relevant, gut begründet | openkubes/openkubes (architecture/decisions/) bleibt | **keep as-is, migrate to docs/adr/ format consistency** |
| Reference Architecture v1 (4 Zonen) | architecture/ | Management/Infra/Tenant/Operations Zonen-Modell | Teilweise — Grundidee gut, aber ok-linux/ok-cluster Trennung von gestern ist granularer | openkubes/openkubes | **reconcile mit gestriger Architektur (spec.md, ADRs)** |
| Platform API Tabelle (OpenKubesCluster, OpenKubesVM, etc.) | architecture/README.md | Liste zukünftiger Self-Service-Produkte | Ja — das ist die Plattform-Vision | openkubes/openkubes | **keep, formalize as Platform CRD spec** |
| `platform/virtualization/openkubesvm/` | openkubes/platform | VM-as-a-Service via Crossplane | Ja | ok-local? oder eigener ok-vm? | **needs deeper look — not yet inventoried today** |
| `config/countries/de.env` (POD_CIDR, SERVICE_CIDR, DNS_DOMAIN_SUFFIX) | capi-platform-v4.2/config | Statisches CIDR-Profil pro Region/Datacenter, verhindert Kollisionen bei Multi-Site | Ja — aber `ok-cluster render.py` löst dasselbe Problem bereits automatisch (next-free aus Pool) | ok-cluster (bereits überlegene Lösung vorhanden) | **kein Migrationsbedarf — ok-cluster ist hier bereits weiter** |
| `config/providers/kubevirt.env` → `VM_IMAGE_URL=ubuntu-2404-container-disk` | capi-platform-v4.2/config | VM-Image-Auswahl, ursprünglich Ubuntu-zentriert | Teilweise — Talos-Entscheidung (ok-linux ADR-001) ersetzt diesen Ansatz für neue Cluster | ok-linux (Schematic/Image ownership) | **historisch — bestätigt dass capi-platform-v4.2 vor der Talos-Entscheidung entstand** |
| `networking/`, `hardware/`, `robotics/`, `observability/` | openkubes/platform | Platzhalter, nur README | Noch offen — keine Implementierung vorhanden | TBD je nach Reife | **no action needed yet — pure intent** |

---

## Offene Kernfrage für heute

**Ist `openkubes/openkubes` eine Platform Distribution oder ein Monolith?**

Heute zeigt sich: Es ist beide auf einmal. Die Crossplane XRD/Composition-Schicht ist der Beginn eines echten Plattform-Vertrags (Self-Service-API). Aber `capi-platform-v4.2` als Runner-Implementierung liegt im selben Repo wie der Vertrag selbst — das ist die Monolith-Eigenschaft die GPT gestern vorausgesagt hat.

GPTs Leitsatz von gestern Abend: *"OpenKubes main repo is the distribution and integration layer, not the implementation home for every subsystem."*

Wenn das stimmt, lautet die Konsolidierung:

```
openkubes/openkubes  
  → behält: xrd.yaml, composition.yaml (der Vertrag), architecture/, ADRs
  → gibt ab: capi-platform-v4.2 Runner-Implementierung → wandert in ok-cluster
            (als "Self-Service API Mode" — Composition triggert ok-cluster statt eigenen Runner)
```
