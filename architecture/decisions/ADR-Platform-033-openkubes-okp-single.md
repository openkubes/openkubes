# ADR-Platform-033: OpenKubes OKP Single — Capability Placement and Autonomy

- **Status:** Draft — pending acceptance evidence. Review „Approve with Requested Changes" eingearbeitet (2 Required, 3 Corrections, 2 Präzisierungen); der Architektur-Spike (§14) ist das Acceptance-Gate.
- **Datum:** 2026-08-14
- **Kontext:** OpenKubes Kubernetes Platform (OKE) / OpenKubes AI
- **Betrifft:** Distributions-Topologie der OpenKubes-Plattform und die **Placement- und Autonomy-Semantik** der Plattform-Capabilities (`ok-shared` als Rolle, nicht als Cluster)
- **Nummerierung:** Abgelegt als `architecture/decisions/ADR-Platform-033-openkubes-okp-single.md` (nächste freie Nummer nach `ADR-Platform-032`), konsistent mit der bestehenden Plattform-Serie.
- **Tracking:** Jira `OK-146` (OpenKubes) — Spike-Ausführung & Acceptance-Evidence.
- **Beziehung:** Nutzt dasselbe Contract-/Evidence-Modell wie `ADR-Platform-032` (DBaaS). DBaaS und AI-Services erscheinen hier als *optionale* Capabilities mit eigenem Placement, nicht als Voraussetzung.

> **Framing-Schutz (bewusst):** Dieser ADR entscheidet **nicht** „wir betten alles ein". Er beantwortet die
> größere, langlebigere Frage:
>
> > **Welche OpenKubes-Capabilities dürfen `embedded`, `shared` oder `external` materialisiert werden, und
> > welche überprüfbare Autonomie-Zusicherung ergibt sich aus einer gegebenen Placement-Kombination?**
>
> Konkrete Komponentenwahl (Zot vs. Harbor, HAProxy vs. Envoy, MetalLB vs. kube-vip, StorageClass,
> DNS-Implementierung) ist **ausdrücklich Out of Scope** (§11) und folgt später über Provider-Spikes /
> Composition Records.

> **Hinweis zu Quellen:** Die genannten OpenShift-Fähigkeiten dienen als **Analogie und Design-Grundlage**
> und sind gegen die Zielversionen der gewählten OpenKubes-Provider zu bestätigen — nicht als gesetzte
> OpenKubes-Architektur. Bewusst berücksichtigt: der Image-Registry-Operator startet auf Plattformen ohne
> geeigneten Storage zunächst als `Removed` (Storage muss konfiguriert, Registry aktiviert werden; bei einer
> Replik auch `ReadWriteOnce`), MetalLB adressiert `LoadBalancer`-Services getrennt von der HTTP(S)-
> Ingress-/Router-Ebene, und für disconnected/air-gapped Image-Auflösung ist `ImageContentSourcePolicy`
> deprecated und durch `ImageDigestMirrorSet`/`ImageTagMirrorSet` abgelöst.

---

## 1. Kontext und Problem

OpenKubes trennt konzeptionell einen `ok-shared`-Bereich (Registry, Identity, Vault, Observability,
GitOps …) von den konsumierenden Clustern. Zwei Dinge sind bislang verschmolzen und sollen entflochten
werden:

1. **Placement und Provider.** „Registry" bezeichnet heute implizit sowohl *wo* die Registry läuft als
   auch *welche* Registry es ist. Das koppelt zwei orthogonale Entscheidungen und widerspricht
   **Contracts, not Components**.
2. **Autarkie als Boolean.** „Autark" ist keine binäre Eigenschaft. Ein Cluster kann bei Ausfall von
   `ok-shared` gleichzeitig laufende Pods weiterbetreiben, aber kein noch nicht lokal vorhandenes Image
   ziehen, keine neuen Nodes provisionieren, kein Upgrade fahren und sich nicht vollständig
   wiederherstellen. „Autark ja/nein" verdeckt genau diese Abstufung.

Die naheliegende, aber falsche Antwort wäre, eine **separate „Single-Cluster-Distribution" mit eigener
Semantik** oder eine **feste eingebettete Komponentenarchitektur** zu bauen. Beides würde OpenKubes
gabeln bzw. den OpenShift-Vergleich versehentlich in eine gesetzte Komponentenwahl übersetzen. Dieser
ADR verhindert beides, indem er **Placement** und **Autonomy** als Contracts modelliert und die
Provider-Wahl explizit vertagt.

> **Definition:** „OKP Single" bezeichnet eine **Single-Cluster-/Single-Installation-Topologie**, **nicht
> Single Node**. Node-Zahlen (z.B. 3–6) sind ein mögliches Produktprofil, keine Architekturdefinition — der
> Begriff darf nicht mit SNO gleichgesetzt werden.

## 2. Entscheidungstreiber

- Konsistenz mit **Contracts, not Components** — Placement und Provider strikt orthogonal.
- **Ein** Architektur-/Contract-Modell für alle Topologien; die Distribution ist eine **Policy**, kein Fork.
- **Überprüfbare** Autonomie statt eines Bauchgefühl-Booleans — Blast Radius wird evidenzierbar.
- Ehrlichkeit über die **Bootstrap-Grenze** (Henne-Ei bei API-Erreichbarkeit, DNS, Seed-/Mirror-Images).
- **Recovery-Souveränität**: kollokierte Plattformdienste dürfen die Reparierbarkeit des Clusters nicht
  an sich selbst binden.
- Vertagung der Komponentenwahl auf Provider-Spikes — die Contract-Grenze bleibt provider-neutral.

## 3. Kernentscheidung — zwei orthogonale Achsen: Placement und Provider

Jede Plattform-Capability hat **zwei unabhängige** Entscheidungen. `placement` sagt *wo* materialisiert
wird; `provider`/`providerRef` sagt *womit*.

```text
Capability
   │
   ├── placement ─────┬── embedded   (innerhalb der OKP-Single-Installations-/Lifecycle-Boundary)
   │                  ├── shared     (Referenz auf eine ok-shared-Materialisierung)
   │                  └── external   (Drittanbieter / Bring-your-own, außerhalb ok-shared)
   │
   └── provider ──────┬── (registry) zot | harbor | quay | distribution | …
                      ├── (ingress)  traefik | envoy-gateway | nginx | haproxy | …
                      └── (serviceLB) metallb | kube-vip | external | …
```

Nicht: `registry.provider: embedded`. Sondern:

```yaml
registry:
  placement: embedded
  provider: zot
identity:
  placement: shared
  providerRef: ok-shared-identity
```

**Distributions-Topologie ist eine Policy**, kein zweites OpenKubes: `topology: single | multi` rendert
**dieselben Contracts** auf unterschiedliche Placement-Defaults. Der Verbund-Deskriptor:

```yaml
apiVersion: platform.openkubes.org/v1alpha1
kind: OKPDistribution
spec:
  topology: single                 # single | multi
  autonomy:
    objective: runtime             # siehe §5 — validierbare Leiter
  capabilities:
    registry:            { placement: embedded, provider: zot }
    controlPlaneEndpoint:{ placement: embedded, provider: kube-vip }
    serviceLoadBalancer: { placement: embedded, provider: metallb }
    ingress:             { placement: embedded, provider: envoy-gateway }
    certificates:        { placement: embedded }
    identity:            { placement: shared,   providerRef: ok-shared-identity }
    secrets:             { placement: embedded }
    observability:       { placement: embedded }
    gitops:              { placement: embedded }
    # optional:
    # dbaas:             { placement: embedded }   # nutzt ADR-032-Contract
    # ai:                { placement: embedded }
```

**Prinzip:** *OKP Single is not a stripped-down OpenKubes. It is the same platform architecture under a
placement policy plus an autonomy objective.*

### 3.1 Präzedenz — Topologie liefert Defaults, Placement materialisiert, Autonomy constraint

`topology` ist **nur Profil/Default**, kein zweiter Semantikschalter. Die Auflösung ist strikt geordnet,
damit `single`/`multi` und explizites Placement nie um dieselbe Entscheidung konkurrieren:

```text
distribution.type = single
        ↓ liefert Placement-Defaults
Capability-Placement darf explizit überschrieben werden
        ↓
Autonomy-/Contract-Validator prüft, ob die resultierende Composition zulässig ist
```

**Kernsatz:** *Distribution topology selects defaults. Capability placement selects materialization.
Autonomy objectives constrain valid combinations.* Bei Konflikt gewinnt immer das **explizite Placement**
über das Topologie-Default; die **Autonomy-Validierung (§5.1) hat das letzte Wort** über Zulässigkeit.

## 4. `ok-shared` neu definiert — Rolle, nicht Cluster

`ok-shared` bezeichnet **nicht länger einen Cluster**, sondern eine **OpenKubes Capability Composition für
gemeinsam genutzte Plattformdienste**. Placement ist ein Attribut **je Capability**; Single/Multi sind nur
zwei Ecken eines Kontinuums, ohne dass Consumer-Contracts sich ändern.

```text
OKP Single            OKP Multi              gemischt (später möglich)
registry:  embedded   registry:  shared      registry:      embedded
identity:  shared     identity:  shared      identity:      external
secrets:   embedded   secrets:   shared      observability: shared
observ.:   embedded   observ.:   shared      secrets:       external
```

Konsumenten (Workloads, `ok-ai`, DBaaS) referenzieren **denselben Capability-Contract**, unabhängig vom
Placement. Verschieben von `embedded → shared → external` ändert die Consumer-Referenz **nicht**.

## 5. Autonomy Objectives — die überprüfbare Definition von Autarkie (orthogonal zu Placement)

Autonomy ist eine **eigene Contract-Dimension**, orthogonal zu `placement`: `placement` sagt *wo* eine
Capability materialisiert wird, `autonomy.objective` sagt, *welche Betriebsfähigkeit bei Verlust von
`ok-shared` zugesichert* ist. Statt „autark ja/nein" definiert OKP eine **geordnete, kumulative Leiter**;
jedes Objective bestimmt eine **Dependency Closure** (§5.1), aus der der Renderer die zulässigen
Placement-/Provider-Kombinationen **ableitet** — nicht umgekehrt.

| Objective      | Zugesicherte Operation ohne `ok-shared`                                           | initiale Dependency-/Constraint-**Hypothese** (Spike darf widerlegen) |
| -------------- | --------------------------------------------------------------------------------- | ---------------------------------- |
| `runtime`      | bestehende Workloads laufen weiter                                                | kein `ok-shared`-Control-Path nötig |
| `restart`      | vorhandene Workloads/Pods können neu gestartet werden                             | benötigte Images lokal vorhanden (embedded registry / gemirrort) |
| `reconcile`    | Controller/GitOps reconciliieren weiter (inkl. Scale neuer Endpoints)            | gitops + ingress + serviceLoadBalancer embedded; controller-auth nicht an shared identity gebunden |
| `recovery`     | Plattform kann ohne `ok-shared` wiederhergestellt **und aktualisiert** werden     | externer Recovery-Pfad für Registry-Daten & Secrets; Break-glass (§8); Upgrade-/Ziel-Images lokal |
| `disconnected` | benötigte Artefakte **und Dienste** sind lokal verfügbar; Installation offline (wieder-)aufbaubar | L0-Seed-/Mirror-Images vollständig lokal; alles offline auflösbar |

> Die dritte Spalte ist **Hypothese, nicht Architekturregel**: sie nennt die *vermutete* Closure, deren
> tatsächliche Auflösung der Spike ermittelt. Die normative Ableitung steht in §5.1.

Kumulativ: `disconnected` ⊃ `recovery` ⊃ `reconcile` ⊃ `restart` ⊃ `runtime`. (`scale` ist vorerst in
`reconcile` gefaltet, `upgrade` in `recovery`.) **Fünf Objectives sind die aktuelle Contract-Hypothese,
nicht etwas, das der Spike um jeden Preis bewahren muss:** zeigt der Spike unterschiedliche Dependency
Closures für „reconcile" vs. „neue Pods/Endpoints skalieren" bzw. „restore" vs. „upgrade", darf er die
Werte wieder aufbrechen.

### 5.1 Der Renderer validiert Objective × Placement (statt zu hoffen)

Das ist das stärkste OpenKubes-Element dieses ADR: das angeforderte Objective erzeugt eine
**Placement-Constraint-Menge**, die der Renderer als **Contract-Validierung** auswertet. Eine
Kombination, die das Objective nicht erfüllen kann, **schlägt fehl** — sie wird nicht optimistisch
gerendert.

```text
autonomy:
  objective: disconnected
identity:
  placement: shared           # Controller/Recovery bräuchten ok-shared-Identity
        │
        ▼
CONTRACT VALIDATION FAILS:
  objective 'disconnected' requires identity resolvable offline,
  but identity.placement=shared depends on ok-shared reachability.
```

statt „wird vermutlich schon gehen". Formal ist das Autonomy-Erfüllen eine **beweispflichtige** Zusage im
Sinne von ADR-032 (`Stale ≠ Failed`, zeitlich begrenzte, widerrufbare Evidence): der Blast Radius wird
**evidenzierbar** statt behauptet.

**Architekturregel — Ableitung aus der Dependency Closure, nicht aus Placement-Labels:**

```text
Autonomy Objective
       ↓ promised operations
mandatory dependency closure
       ↓ failure / reachability boundary
valid placement / provider combinations
       ↓
renderer constraint
```

> **Autonomy constraints MUST be derived from the mandatory dependency closure of the requested objective,
> not from placement labels alone.** For every operation guaranteed by an autonomy objective, all mandatory
> dependencies MUST remain resolvable within the declared autonomy boundary while `ok-shared` is
> unavailable.
>
> - `placement=embedded` normally places a dependency **inside** that boundary.
> - `placement=shared` places the dependency **outside** that boundary by definition (it depends on `ok-shared`).
> - `placement=external` MUST be evaluated against its **actual reachability and failure dependency** — it is
>   **not** automatically autonomy-hostile (a local-DC DNS, storage system, HSM, or registry can be fully
>   independent of `ok-shared`).
>
> The exact dependency closure and the resulting placement constraints per objective are **determined by the
> architecture spike and become normative only with acceptance evidence.**

Die richtige Renderer-Frage ist damit *„ist diese Dependency für das angeforderte Objective noch
verfügbar?"* — **nicht** *„ist sie `embedded`?"*. `external ≠ nicht-autark`.

### 5.2 Pull-Through-Cache ist Bandbreite, nicht Autonomie (bindet an INV-2 / INV-4)

Ein Pull-Through-Cache auf `ok-shared` **darf** die Image-Beschaffung beschleunigen, **darf aber nicht**
zur Erfüllung eines Autonomy Objectives erforderlich sein:

```text
A shared pull-through cache MAY accelerate image acquisition,
but MUST NOT be required to satisfy an autonomy objective.

For disconnected autonomy, every required recovery/runtime image
MUST be available through an independently recoverable local or
otherwise autonomy-compliant image source.
```

„Cache-Miss = nur langsamer, nicht kaputt" gilt **nur** unter Fallback-Bedingung — solange ein anderer
erreichbarer Upstream existiert. Genau diese Semantik ist explizit modellierbar: bei
`ImageDigestMirrorSet` steuert `mirrorSourcePolicy`, ob nach fehlgeschlagenen Mirrors noch auf die Source
zurückgefallen werden darf (ohne explizites Verbot wird die Source weiter versucht). Für `objective:
disconnected` müssen benötigte Images dagegen **vorab** in die erreichbare Mirror-Umgebung gebracht
werden. Referenzmodell daher `ImageDigestMirrorSet`/`ImageTagMirrorSet` — **nicht** das deprecatete
`ImageContentSourcePolicy`. Damit hängt §5.2 direkt an **`INV-2`** (Recovery ohne embedded Registry) und
**`INV-4`** (Bootstrap-/Mirror-Images unabhängig wiederherstellbar).

## 6. Bootstrap-Grenze (L0/L1)

Nicht alles kann sich als normaler Kubernetes-Workload selbst starten: der API-Endpoint muss erreichbar
sein, **bevor** Kubernetes Deployments ausführt (Henne-Ei). Deshalb die Zwei-Ebenen-Zerlegung:

```text
L0 — Bootstrap Plane   (außerhalb / vor Kubernetes; so klein wie möglich)
├── ControlPlaneEndpoint / API VIP     (kube-vip static pod | keepalived/HAProxy | external LB — Spike-Wahl)
├── Bootstrap DNS
├── Seed / Mirror images                (lokale Quelle; für objective: disconnected vollständig offline)
└── Node configuration                  (Talos / Flatcar / Ubuntu)
        ↓ cluster becomes Ready
L1 — Embedded Platform  (alles als verwaltete In-Cluster-Workloads)
OCI Registry · Ingress · ServiceLoadBalancer · Certificates ·
Identity · Secrets · Observability · GitOps · Storage · optional DBaaS/AI
```

**Wichtig:** `MetalLB` gehört **nicht** in L0. Es stellt externe IPs für `LoadBalancer`-Services auf der
**laufenden** Cluster-/Service-Ebene bereit und ist damit die `serviceLoadBalancer`-Capability in L1 —
nicht der Control-Plane-Endpoint. Der API-VIP (L0) muss existieren, *bevor* Kubernetes-Services überhaupt
auflösen; ein Service-basierter Mechanismus kann diesen Teil per Definition nicht bootstrapen.

**Leitprinzip:** *Bootstrap as little as possible outside Kubernetes. Run everything else inside
Kubernetes.* L0 ist provider-neutral und minimal; das höchste Objective (`disconnected`) verlangt, dass L0
**vollständig lokal/offline** auflösbar ist.

**Definition `embedded` (umfasst L0):** `placement: embedded` heißt **innerhalb der OKP-Single-
Installations- und Lifecycle-Boundary materialisiert** — nicht zwingend „als In-Cluster-Workload".
**L0-Capabilities** (z.B. `controlPlaneEndpoint`) MAY als Host-/Static-Pod-/Bootstrap-Mechanismus
materialisiert werden (sie existieren vor Kubernetes); **L1-Capabilities** werden als verwaltete
In-Cluster-Workloads materialisiert. Damit bleibt **ein** Placement-Begriff gültig, ohne L0 künstlich als
`external` behandeln zu müssen — `controlPlaneEndpoint: { placement: embedded }` in C0 ist also korrekt.

## 7. Capability-Zerlegung — Netzwerk sind drei Capabilities, Registry ist ein Contract

`Ingress/LB` als eine Einheit ist zu grob: HAProxy, VIP und MetalLB lösen **unterschiedliche** Probleme.
Deshalb drei getrennte Capabilities:

```yaml
controlPlaneEndpoint:               # API-Erreichbarkeit (L0)
  placement: embedded               # provider: direct | kube-vip | keepalived/HAProxy
  # oder: { placement: external, providerRef: datacenter-api-lb }
serviceLoadBalancer:                # externe IPs für Service type=LoadBalancer (Bare Metal)
  placement: embedded               # provider: metallb | kube-vip (service mode)
  # oder: { placement: external, providerRef: datacenter-lb }
ingress:                            # HTTP(S)-Ingress / L7-Routing
  placement: embedded               # provider: traefik | envoy-gateway | nginx | haproxy
```

**Hinweis (Orthogonalität, letzte Konsequenz):** `external` ist ein **Placement**, kein Provider. Ein
Provider-Slot enthält nie `external`; stattdessen `placement: external` + `providerRef` auf das externe
System. Das ist keine neue Entscheidung, nur die Durchsetzung von §3.

Das verhindert, dass ADR-033 jemals HAProxy mit „dem Load Balancer" gleichsetzt (der Router löst
HTTP(S)-Ingress; MetalLB stellt auf Bare Metal externe IPs für `LoadBalancer`-Services bereit — getrennte
Verantwortlichkeiten).

**Registry** wird als **Contract** modelliert, nicht als Produktwahl:

```text
OCI Registry Contract  →  Zot | Harbor | Quay | CNCF Distribution | …
   fixiert: Push/Pull · Storage-Backend · GC · Quota · Provenance · Recovery-Pfad
```

Es gilt **nicht** `OpenKubes Registry == Harbor`.

## 8. Recovery- & Autonomy-Invarianten

Wenn Registry, Identity und Secrets `embedded` liegen, darf ihr Ausfall den Cluster nicht unreparierbar
machen. Diese Invarianten binden die Objectives `recovery`/`disconnected` und sind **implementierungs-neutral**:

```text
INV-1  Cluster Recovery MUST NOT require embedded identity (Keycloak).
INV-2  Cluster Recovery MUST NOT require the embedded registry.
INV-3  Break-glass access MUST remain available, independent of embedded identity.
INV-4  Bootstrap/mirror images MUST be recoverable independently (L0 seed path survives).
INV-5  Registry data MUST have an external recovery path.
INV-6  Secrets MUST have an independently restorable backup.
```

Sie sind wichtiger als jede konkrete Provider-Wahl (HAProxy/kube-vip/MetalLB/Harbor/Zot) und werden im
Spike per Break-glass-Drill praktisch nachgewiesen.

## 9. Abgrenzung zu OpenShift (korrigiert — und dadurch stärker für uns)

OpenShift **behauptet nicht**, dass jede Infrastruktur dieselbe Registry-Materialisierung hat: der
Image-Registry-Operator startet auf Plattformen ohne geeigneten Storage zunächst als `Removed`; Storage
muss konfiguriert und die Registry aktiviert werden (bei einer Replik auch `ReadWriteOnce`). Genau das ist
die Aussage, die wir wollen:

> *OpenShift integriert die Registry als Capability in die Distribution, ohne zu behaupten, dass jede
> Umgebung sie identisch materialisiert.*

OKP Single macht dasselbe — nur explizit als `placement` + `provider` + `autonomy.objective`. Der Gewinn
gegenüber OpenShift: **austauschbare Provider hinter den Contracts** statt fester Distributionskomponenten.

## 10. In Scope

Capability **Placement** (`embedded | shared | external`), **Autonomy Objectives** und ihre Renderer-
Validierung, **Failure Dependencies** / Blast Radius, **Bootstrap Boundary** (L0/L1), **Provider
Resolution** (Contract-Ebene) und **Conformance** (was ein Objective beweisen muss).

## 11. Out of Scope (explizit — bewusst vertagt)

```text
Zot vs. Harbor vs. Quay vs. Distribution        (Provider-Spike)
HAProxy vs. Envoy vs. Traefik vs. nginx         (Provider-Spike)
MetalLB vs. kube-vip                            (Provider-Spike)
konkrete StorageClass / CSI-Wahl               (Provider-Spike)
konkrete DNS-Implementierung                    (Provider-Spike)
```

Diese Auswahlentscheidungen kommen danach über Provider-Spikes oder Composition Records — **nicht** in
diesem ADR.

## 12. Non-Goals für v1 & Claims we intentionally do not make

```text
Non-goals v1
──────────────
Eine zweite OpenKubes-Distribution mit eigener Semantik (es ist Policy, kein Fork)
Vollständige Selbst-Hostung der L0-Bootstrap-Plane
Beliebige Placement-Matrix pro Capability als getestete GA-Topologie (Kontinuum ist Ziel, nicht v1-Scope)
Kommerzielle SLA / 24x7 Accountability für eingebettete Dienste
Zwingende DBaaS-/AI-Aktivierung (bleiben optionale Capabilities)
```

- `placement: embedded` weakens **no** Capability Contract relative to `shared`/`external`.
- A **pull-through cache** is **not** an autonomy mechanism (see §5.2).
- A chosen **provider** is **not** part of the architecture — only its contract is.
- „Integrated distribution" does **not** imply a fixed, non-replaceable component set.
- A **requested** `autonomy.objective` is **not** evidence of autonomy — the renderer must validate it, and
  runtime evidence must confirm it (ADR-032 Evidence-Modell).

## 13. Zu entscheidende Semantik (Acceptance-relevant)

**13.1 Placement-Contract-Äquivalenz (Binding, nicht aufgelöster Wert).** Das Verschieben einer Capability
zwischen `embedded`, `shared` und `external` **MUST NOT** eine Änderung am *Contract-Schema*, am
*Binding-Mechanismus* oder an der *deklarierten Dependency* des Consumers erfordern. **Provider-aufgelöste
Werte (Hostname, Zertifikat, Secret-Inhalt, Endpoint, Provider-Binding) MAY differ.** Das ist die
eigentliche Fitness Function — nicht Byte-Gleichheit:

```text
Consumer:            registryRef: platform-registry     # Binding-Contract bleibt stabil

embedded   → registry.okp.internal
shared     → registry.shared.openkubes.example
external   → harbor.customer.example                    # nur der aufgelöste Wert variiert
```

(Detail: §3–§4)

**13.2 Autonomy-Objective-Semantik & Validierung.** Die Leiter (§5) ist verbindlich; der Renderer muss
unerfüllbare Objective×Placement-Kombinationen **ablehnen** statt optimistisch rendern. (Detail: §5.1)

**13.3 Disconnected = lokale Image-Präsenz.** `objective: disconnected` verlangt lokal gemirrorte Images
(Modell: `ImageDigestMirrorSet`/`ImageTagMirrorSet`), **nicht** Pull-Through-Cache. (Detail: §5.2)

**13.4 Recovery-Invarianten INV-1..INV-6.** Harte, implementierungs-neutrale Invarianten; Nachweis per
Break-glass-Drill an eingebettetem Identity- **und** Registry-Provider. (Detail: §8)

## 14. Path to Acceptance — Architektur-Spike mit forcing consumer

```text
Proposed ADR
│  ├── trennt placement ⊥ provider
│  ├── definiert die validierbare Autonomy-Objective-Leiter
│  ├── zerlegt Netzwerk in ControlPlaneEndpoint/ServiceLoadBalancer/Ingress
│  ├── setzt Recovery-Invarianten INV-1..INV-6
│  └── benennt In/Out-of-Scope (§10/§11)
▼  Spike established as acceptance gate
Draft — pending acceptance evidence
▼
Architecture Spike — forcing consumer:
  eine konkrete OKP-Single-Composition, die MINDESTENS
    Registry + Ingress + ServiceLoadBalancer   → placement: embedded
  rendert, und anschließend DEMONSTRIERT, was bei Verlust von ok-shared
  je Autonomy-Objective (runtime → … → disconnected) noch funktioniert.
▼
Evidence + Decision
▼
ADR  →  Accepted | revised | rejected
```

**Zentrale Frage:** *Can OpenKubes render identical Capability Contracts under a `placement` policy, and
can the renderer prove — not assume — that a given placement combination satisfies the requested
`autonomy.objective` when `ok-shared` is unreachable?*

**Forcing consumers — jeder setzt eine Annahme unter Druck:**

```text
OKP-Single-Composition (Registry+Ingress+ServiceLB embedded) → forces placement realizability
autonomy.objective sweep (runtime→disconnected)              → forces objective/placement validation
ok-shared-outage drill                                        → forces blast-radius evidence
break-glass recovery drill                                    → forces INV-1..INV-6
disconnected rebuild                                          → forces local-image (mirror) semantics
```

**Acceptance-Kriterium:** `Accepted`, wenn der Spike §13.1–§13.4 je entschieden liefert, die
Objective-Validierung (§5.1) an mindestens einer *ablehnenden* und einer *erfüllenden* Kombination
demonstriert, und die Invarianten §8 per Drill nachweist. Weder ein konkreter Provider noch der
Composition-Mechanismus werden vorausgesetzt — sagt der Spike, dass eine bestimmte Wahl sinnvoll ist, ist
sie **Resultat**, nicht Ausgangsannahme.

## 15. Offene Fragen — dem Spike überlassen

- Composition-/Rendering-Mechanismus für `OKPDistribution` (dünner Controller, GitOps-Overlays, Admission
  + Manifeste, oder — falls dann verbindlich — Crossplane). Konsistent mit der offenen `???`-Frage aus
  ADR-032 §12.
- Ab wann die **gemischte** Placement-Matrix (§4) über Single/Multi hinaus als getestete Topologie GA geht.
- Genaue Objective × Dependency-Closure × Placement-Matrix. Bewusst **nicht** normativ in diesem ADR; sie
  ist das **erste Spike-Artefakt** (siehe `architecture/spikes/SPIKE-Platform-033-okp-single-autonomy.md`)
  und wird erst mit Acceptance-Evidence normativ (§5.1).

---

## Referenzen (Design-Grundlage, im Spike gegen Zielversion zu bestätigen)

- OpenShift 4.22 — Registry: Image-Registry-Operator auf Plattformen ohne geeigneten Storage zunächst
  `Removed`; Storage konfigurierbar; `ReadWriteOnce` bei einer Replik
  (docs.redhat.com — registry, 4.22).
- OpenShift 4.22 — MetalLB Operator: externe IPs für `LoadBalancer`-Services auf Bare Metal, getrennt von
  der HTTP(S)-Ingress-/Router-Ebene (docs.redhat.com — networking_operators / metallb-operator, 4.22).
- OpenShift 4.22 — Disconnected environments: Image-Mirror-Modell; `ImageContentSourcePolicy` deprecated,
  abgelöst durch `ImageDigestMirrorSet`/`ImageTagMirrorSet` (docs.redhat.com — disconnected_environments, 4.22).
- OpenKubes — ADR-Platform-032 (DBaaS): Contract-/Evidence-Modell, „Contracts, not Components",
  `Stale ≠ Failed` (interne Referenz).
- L0-Node-OS-Kandidaten: Talos, Flatcar, Ubuntu. Registry-Provider-Kandidaten: Zot, Harbor, Quay,
  CNCF Distribution. **ControlPlaneEndpoint/API-VIP (L0)**-Kandidaten: kube-vip static pod,
  keepalived/HAProxy, external LB. **ServiceLoadBalancer (L1)**-Kandidaten: MetalLB, kube-vip service mode.
  (alle Provider-Spike, §11)
