# SPIKE-Platform-033: OKP Single — Objective × Dependency-Closure × Placement × Evidence

- **Status:** Open — erstes Artefakt zu `ADR-Platform-033` (Draft — pending acceptance evidence)
- **Datum:** 2026-08-14
- **Tracking:** Jira `OK-146` (OpenKubes).
- **Gate für:** `ADR-Platform-033` (§14). Das Ergebnis dieses Spikes wird — und erst dann — zur **normativen**
  Objective-Constraint-Matrix des ADR.
- **Ablage:** `architecture/spikes/SPIKE-Platform-033-okp-single-autonomy.md`

> **Zweck & Grenze:** Dieses Dokument enthält **Hypothesen, keine Entscheidungen**. Es setzt die
> Architekturregel aus ADR-033 §5.1 in eine testbare Matrix um. Die hier notierten Placement-Vermutungen
> dürfen vom Spike widerlegt werden; normativ wird nur, was am Ende durch Failure-Drills belegt ist.

---

## 1. Leitregel (aus ADR-033 §5.1)

> Autonomy constraints MUST be derived from the **mandatory dependency closure** of the requested objective,
> not from placement labels alone.

```text
Autonomy Objective
   ↓ promised operations
mandatory dependency closure
   ↓ failure / reachability boundary
valid placement / provider combinations
   ↓
renderer constraint
   ↓
failure drill
   ↓
evidence  →  (erst hier) normative Matrix
```

Kernfrage je Dependency: *„Ist diese Dependency für das angeforderte Objective noch verfügbar, während
`ok-shared` weg ist?"* — **nicht** *„ist sie `embedded`?"*. Damit bleibt `external ≠ nicht-autark`.

## 2. Hypothesenmatrix A — Objective → Operation → Dependency Closure → Negative Test

Jede Zeile ist eine **zu widerlegende Ausgangshypothese**. Der „Negative Test" ist der Failure-Drill, der
`ok-shared` (bzw. die vermutete Dependency) entzieht und misst, ob die zugesicherte Operation überlebt.

| Objective      | Zu beweisende Operation                                                | Dependency Closure — Ausgangshypothese                                                                 | Negative Test                                        |
| -------------- | ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| `runtime`      | bestehende Workloads laufen weiter                                     | kubelet/runtime, CNI, Storage/Data Plane; **kein** notwendiger `ok-shared`-Control-Path               | `ok-shared` netzwerkseitig isolieren                 |
| `restart`      | vorhandener Workload kann neu starten                                  | Image + Config + Secret + Storage ohne `ok-shared` auflösbar; Kube-API + Scheduler erreichbar          | R1 same-node restart · **R2 cold reschedule** (Image nicht gecacht) |
| `reconcile`    | Desired State weiter umsetzbar, inkl. neuer Endpoints/Pods             | Git/Desired State, Controller-Credentials, Kube-API, Images, Networking; keine mandatory shared Dep.   | Deployment ändern / skalieren                        |
| `recovery`     | Plattform wiederherstellen **und** aktualisieren                       | Backup, Break-glass, Secrets, Recovery-/Upgrade-Artefakte, L0-Zugriff (INV-1..INV-6)                   | eingebettete Registry/Identity verlieren + Restore   |
| `disconnected` | Installation vollständig offline reproduzieren                        | komplette L0+L1 Artefakt-/Credential-/Config-Closure lokal bzw. autonomy-compliant                     | neues OKP Single ohne Upstream/`ok-shared` aufbauen  |

### 2.1 Kandidaten-Sub-Objectives, die der Spike gezielt challengen soll

Fünf Objectives sind die aktuelle Contract-Hypothese (ADR-033 §5). Der Spike prüft, ob folgende Aspekte
eine **eigene** Dependency Closure haben und deshalb als eigener Enum-Wert wieder aufzubrechen sind:

| Kandidat  | gefaltet in  | Aufbrechen, falls …                                                            |
| --------- | ------------ | ----------------------------------------------------------------------------- |
| `scale`   | `reconcile`  | „neue Pods/Endpoints skalieren" braucht Scheduling-/Provisioning-/Networking-Control-Path, den bloßes Reconcile nicht braucht |
| `upgrade` | `recovery`   | „Zielartefakte + Upgrade-Control-Path" unterscheiden sich messbar von „Restore aus Backup" |

### 2.2 Forcing-Consumer-Probe je Objective (Closure ist die des Consumers, nicht aller Workloads)

`required=yes` ist **keine** globale Aussage über alle Kubernetes-Workloads — nicht jeder Pod braucht
Storage + Ingress + ServiceLB. C0 definiert deshalb je Objective einen **Probe-Workload**, dessen konkrete
Closure gemessen wird. Ingress und der LoadBalancer-Service sind **zwei getrennte Zugangswege** (der Ingress
nutzt den ClusterIP-Service als Backend und traversiert **nicht** die externe LB-IP), daher **zwei parallele
Probes** (Manifest: `okp-single-spike-C0-runtime-probe.yaml`):

```text
Probe A — Ingress:     external client → Ingress controller → ClusterIP svc → Pod → PVC
Probe B — ServiceLB:   external client → LoadBalancer IP    → Pod → PVC

im Pod AKTIV (nicht nur deklariert), alle 5s, für den Drill-Zeitraum geloggt:
   → wiederholter Cluster-DNS-Lookup
   → wiederholter PVC Write→Read unter /data
```

Erst der **aktive** Loop belegt die Data-Plane-Zeilen: ein gemounteter PVC beweist Storage nur teilweise,
eine Env-Var beweist DNS gar nicht. Damit sind `cluster-dns`, `storage-csi-data-plane-mounted`,
`ingress-data-plane-existing-routes` und `serviceloadbalancer-data-plane-provisioned` **einzeln** belegbar —
die Closure genau dieses Consumers, nicht eine Behauptung über beliebige Workloads.

**Zwei Endpunkte, damit ein reiner Reachability-Drill nicht grün lügt:** ein externer Zugriff, der nur
„200 vom Pfad" prüft, wäre PASS, obwohl DNS/PVC still failen. Der Probe trennt deshalb:

```text
/healthz   → 200 solange Prozess lebt  → NICHT an Autonomy-Evidence gekoppelt
             (Liveness/Readiness zeigen hierauf → DNS/PVC-Ausfall startet den Container NICHT neu,
              sonst testet der runtime-Drill versehentlich restart-Semantik)
/evidence  → dns: PASS|FAIL · pvc: PASS|FAIL · timestamp · staleAfter
             200 nur wenn beide frisch PASS, sonst 503
```

Der Drill scraped `/evidence` über **beide** Wege und belegt so unabhängig Ingress-Data-Plane,
ServiceLB-Data-Plane, Cluster-DNS und Storage-Data-Plane:

```text
A:  Ingress → ClusterIP → /evidence   → {dns, pvc} PASS?
B:  LoadBalancer IP     → /evidence   → {dns, pvc} PASS?
```

**Ausführungs-Vorbedingung:** weil der Probe **selbst** Evidence erzeugt, ist sein Image ein
**digest-gepinntes Spike-Fixture** (`probe/Dockerfile`, `probe/app.py`) — kein Utility-Image zur Laufzeit.
`image: …@sha256:PIN-ME` muss vor der ersten `runtime evidence PASS|FAIL` aufgelöst sein.

## 3. Hypothesenmatrix B — Per-Dependency-Evaluation (das eigentliche Spike-Werkzeug)

Nicht „Objective = diese Placements", sondern: jede einzelne Dependency wird gegen das Objective bewertet.
Diese Tabelle wird je Kandidat-Composition ausgefüllt.

```text
Dependency
│
├── Required by objective?          (ja/nein je Objective-Rung)
├── placement                        (embedded | shared | external)
├── provider                         (konkreter Kandidat)
├── failure domain                   (OKP-Single | ok-shared | Drittsystem)
├── reachable with ok-shared down?   (ja/nein — der entscheidende Test)
├── recoverable independently?       (INV-Bezug, wo relevant)
└── Evidence / test                  (welcher Drill belegt es, TTL der Evidence)
```

**Spaltenvorlage (CSV-tauglich):**

```text
dependency, objective, required, placement, provider, failureDomain, reachableWhenSharedDown, recoverableIndependently, evidenceRef
```

Typische Dependencies, die je Objective zu führen sind: Container-Images · GitOps-Desired-State ·
Controller-Credentials · Kube-API/ControlPlaneEndpoint · Ingress · ServiceLoadBalancer · DNS · Certificates/CA ·
Secrets/Vault · Storage/CSI · Backups · Break-glass-Zugang · L0-Seed-/Mirror-Images · Node-Config.

### 3.1 Zwei Validitätszustände — `constraintValid` vs. `evidenceValid`

Das Spike-Modell unterscheidet strikt zwischen statischer Erfüllbarkeit und belegter Erfüllung — und beide
sind **mehrwertig**, kein Boolean (das ist später für den Renderer wertvoller):

```text
constraintValid ∈ { TRUE, FALSE, UNKNOWN }
  FALSE    ≥1 required Dependency ist innerhalb der Autonomy-Boundary unerreichbar
  UNKNOWN  ≥1 Dependency ist required=tbd, oder ihre Reachability ist noch nicht bekannt
  TRUE     alle mandatory Dependencies sind statisch autonomy-compliant

evidenceValid ∈ { PASS, FAIL, STALE, PENDING }
  PENDING  noch keine Drill-Evidence
  PASS     alle required Dependencies haben frische, bestandene Evidence
  FAIL     ≥1 required Dependency hat fehlschlagende Evidence
  STALE    Evidence existiert, ist aber älter als ihre TTL (aus Freshness gefallen)
```

Aktueller Stand:

```text
C0 × runtime :  constraintValid = TRUE     evidenceValid = PENDING
C0 × restart :  constraintValid = UNKNOWN  evidenceValid = PENDING   # identity.required = tbd
```

Eine Autonomy-Zusage gilt erst als belegt, wenn `constraintValid = TRUE` **und** `evidenceValid = PASS`.
„Predicted VALID" ≠ „evidenced VALID".

**Evidence ist zeitgebunden (ADR-032-Modell):** eine bestandene Drill-Evidence hat eine TTL und einen
gemessenen Drill-Zeitraum. `controlPlaneEndpoint required=no` ist für den **laufenden** Data Plane
plausibel, aber **nicht unbegrenzt** — Zertifikatsablauf, Pod-/Node-Ausfall usw. können eine bisher nicht
benötigte Dependency später `required=yes` werden lassen. Jede Zeile führt daher `observedAt`/`validUntil`
implizit über `evidenceRef`; eine veraltete Evidence fällt von `evidenceValid=true` zurück auf `Stale`.

## 4. Warum diese Reihenfolge (statt zuerst Provider zu wählen)

Aus einer belegten Dependency-Closure ergibt sich **natürlich**, welche konkrete OKP-Single-Composition der
forcing consumer braucht — die Providerwahl (Zot vs. Harbor, Envoy vs. HAProxy, MetalLB vs. kube-vip) fällt
danach fast von selbst und bleibt bis dahin bewusst offen (ADR-033 §11).

```text
objective → dependency closure → constraints → evidence → (dann erst) provider/composition
```

## 5. Forcing consumer & Drills (aus ADR-033 §14)

Minimal-Composition: `registry + ingress + serviceLoadBalancer → placement: embedded`, dann Sweep der
Objectives `runtime → restart → reconcile → recovery → disconnected` mit den Negative Tests aus §2.
Pflicht-Drills:

```text
ok-shared-outage drill        → Blast-Radius-Evidence je Objective
break-glass recovery drill    → INV-1..INV-6 (embedded Identity UND Registry verlieren, dann Restore)
disconnected rebuild          → local-image (mirror) Semantik (IDMS/ITMS), objective: disconnected
placement/provider move       → Binding-Contract-Äquivalenz (ADR-033 §13.1): schema/binding/dependency stabil, aufgelöste Werte dürfen variieren
external-independent case      → external Dependency, die ok-shared-unabhängig erreichbar ist (belegt `external ≠ nicht-autark`)
```

### 5.1 `restart`-Drills — R1/R2 (Image-Cache darf nicht mogeln)

Ein Restart-Test mit bereits gecachtem Image beweist nur „Pod startet, solange derselbe Node das Image
noch hat". Deshalb **mindestens zwei** Drills:

```text
R1 — same-node restart
   delete pod → neuer Pod DARF vorhandenen Node-/Image-Cache nutzen
   (belegt: kube-api, scheduler, kubelet, cni, cluster-dns, secret/config, storage-attach)

R2 — cold reschedule
   Image vom Ziel-Node entfernen / alternativen eligible Node erzwingen, dann delete pod
   → Image MUSS ohne ok-shared auflösen (embedded Registry / Mirror)
   → Secret + Config + PVC müssen neu materialisiert werden
   → Pod MUSS Ready werden
   (belegt zusätzlich: container-image-resolution als echte Registry-/Mirror-Dependency)
```

**R2 ist der eigentliche Test**, ob `restart` eine reale Registry-/Mirror-Dependency besitzt oder das
Modell zu optimistisch war.

**Bewusst offen — `identity` nicht vorschnell auf `required=yes`:** wenn ServiceAccount/Auth,
ImagePull-Credentials und Secret-Materialisierung vollständig ohne Keycloak funktionieren, bleibt
`identity: shared` auch bei `restart` irrelevant. Das entscheidet die gemessene Closure (R2), **nicht** die
Erwartung — deshalb steht `identity` in `matrixB-C0-restart.csv` mit `required=tbd`, bis R2 es auflöst.
Solange `identity.required=tbd` ist, ist `restart` **`constraintValid=tbd`** (nicht `true`) — genau die Art
Constraint, die C0 jetzt erstmals produziert.

## 6. Übergang zu normativ

Jede Zeile aus Matrix A wird zu:

```text
Hypothesis → dependency graph → placement constraints → renderer rule → failure drill → evidence
```

Erst das durch Drills belegte Ergebnis wird die **normative** Objective-Constraint-Matrix in ADR-033
(§5.1, §15) und löst zugleich die §13.1–§13.4-artige offene Semantik für OKP Single ab. Bis dahin bleibt
ADR-033 `Draft — pending acceptance evidence`.

---

## Referenzen

- ADR-Platform-033 §5, §5.1, §13.1, §14, §15 (Dependency-Closure-Regel, Binding-Fitness-Function, Spike-Gate).
- ADR-Platform-032: Evidence-Modell (`Stale ≠ Failed`, TTL, widerrufbare Behauptungen) als Vorlage für die
  Evidence-Spalte in Matrix B.
- MetalLB — LoadBalancer-Service-Implementierung (L1 `serviceLoadBalancer`), **nicht** Control-Plane-VIP
  (metallb.io). kube-vip — Control-Plane-VIP, als Static Pod bereits während des kubeadm-Bootstraps startbar
  (L0 `controlPlaneEndpoint`).
- OpenShift 4.22 — `ImageDigestMirrorSet`/`ImageTagMirrorSet` (`mirrorSourcePolicy`) als Referenzmodell für
  die disconnected-Image-Closure; `ImageContentSourcePolicy` deprecated.
