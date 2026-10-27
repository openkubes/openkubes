# ADR-Platform-032: OpenKubes DBaaS — Database Platform Contracts (PostgreSQL Reference)

- **Status:** Proposed — Acceptance-Pfad über den Architektur-Spike definiert (§13); Übergang zu `Draft — pending acceptance evidence`, sobald der Spike als konkretes Acceptance-Gate aufgesetzt ist
- **Datum:** 2026-08-14
- **Kontext:** OpenKubes Kubernetes Platform (OKE) / OpenKubes AI
- **Betrifft:** Data-Capability der OpenKubes-Plattform (`ok-dbaas`, Arbeitstitel)
- **Nummerierung:** Abgelegt als `architecture/decisions/ADR-Platform-032-openkubes-dbaas.md` (nächste freie Nummer nach `ADR-Platform-031`), konsistent mit der bestehenden Plattform-Serie.

> **Hinweis zu Quellen:** Die in diesem ADR genannten CloudNativePG- (CNPG-)Fähigkeiten
> (PITR über neuen Cluster aus Base-Backup + WAL, native `Pooler`/PgBouncer,
> `ImageCatalog`/`ClusterImageCatalog`, mehrere Major-Upgrade-Verfahren mit
> unterschiedlichen Downtime-/Rollback-Profilen) sind **Design-Annahmen auf Basis der
> aktuellen CNPG-Dokumentation** und im Spike gegen die konkret anvisierte CNPG-Version
> zu bestätigen. Sie sind bewusst nicht als gesetzte Wahrheit formuliert — die
> Implementierungs-Viabilität ist Teil der Spike-Frage.

---

## 1. Kontext und Problem

OpenKubes bietet Compute (Kubernetes/OKE) und entwickelt eine AI-Linie (`ok-ai`,
Agenten, OpenWebUI-artige Anwendungen, RAG). Nahezu jede dieser Anwendungen braucht
persistenten State. Wenn OpenKubes Compute + AI abstrahiert, aber jede Anwendung ihre
Datenbank selbst lösen muss, endet die Plattformabstraktion an einer der schwierigsten
Stellen. **Data ist eine auffällige Lücke** in der Capability-Familie.

Die naheliegende, aber falsche Antwort wäre „installiere einen Database-Operator".
Das führt dazu, dass man Operatoren untersucht statt den Plattform-Contract.

## 2. Entscheidungstreiber

- Konsistenz mit dem bestehenden OpenKubes-Prinzip **Contracts, not Components**.
- Konsistenz mit der bestehenden **Evidence-/Readiness-Philosophie**.
- Ehrlichkeit über die Grenzen von Datenbank-Abstraktionen (leaky abstractions).
- Vermeidung von verfrühter Technologie-/Repository-/CRD-Festlegung.
- Die AI-Roadmap erzwingt persistente, standardisierte State-Versorgung.

## 3. Drei Ebenen — und was OpenKubes *nicht* ist

```text
1. DB Platform Capability   OpenKubes kann Datenbanken deklarativ bereitstellen.
2. Self-Service DBaaS       Teams fordern DB-Instanzen über einen stabilen Contract an.
3. Fully Managed DBaaS      Ein Betreiber übernimmt SLA, 24/7, Recovery, Datenverantwortung.
```

**Ebene 1 und 2 sind das Ziel von OpenKubes. Ebene 3 ist eine separate
Geschäftsentscheidung** (die ein Betreiber oder Kubernauts kommerziell darauf aufbauen
kann). OpenKubes betreibt **nicht** die Datenbank des Kunden.

### 3.1 Zwei orthogonale Achsen: Automation vs. Accountability

„Fully Managed" bündelt zwei Dinge, die man trennen muss. OpenKubes will **maximale
Automatisierung bei null Accountability** — Quadrant oben links:

```text
                         Accountability
                    low                  high
              ┌──────────────────┬──────────────────┐
   high       │  OpenKubes       │  Managed DBaaS   │
   Automation │  TARGET          │  Provider        │
              │  max automation  │  max automation  │
              │  no SLA ownership│  + SLA ownership │
              ├──────────────────┼──────────────────┤
   low        │  DIY database    │  bad managed     │
   Automation │  tooling         │  service         │
              └──────────────────┴──────────────────┘
```

**Prinzip:** *OpenKubes automates the hard Day-2 work without assuming contractual
accountability for operating it.* Der Wert der Capability ist proportional zur
automatisierten Day-2-Tiefe — gerade **weil** OpenKubes keine Accountability trägt, ist
die Automatisierung der Hebel, mit dem ein Downstream-Betreiber Accountability *billig*
übernehmen kann. Restore-Verifikation, Failover, Upgrade-Orchestrierung, Credential
Rotation und Backup-Freshness liegen damit ausdrücklich **innerhalb** der Produktgrenze.

## 4. Entscheidung

OpenKubes baut eine **Database Platform Capability** als Satz von Contracts. Der
Operator (CNPG) ist **nicht** das Produkt — der **Lifecycle-/Evidence-Contract ist das
Produkt**. CloudNativePG ist der erste *forcing implementation consumer*, nicht die
Architektur.

### 4.1 Vier Contracts

```text
                 Database Platform Contract
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
   Lifecycle          Service            Evidence
   Contract           Objectives         Contract
        │                  │                  │
        └──────────────────┼──────────────────┘
                           │
                    Capability Contract
                 (engine-specific escape hatch — but governed)
```

**Lifecycle Contract** — portable Betriebssemantik:
`Provision · Connect · Backup · Restore · Upgrade · Failover · Rotate · Delete`

**Service Objective Contract** — messbare Ziele (Objectives, *kein* rechtliches SLA):
`Availability · RPO · RTO · Isolation · Performance · Residency · Maintenance`

**Evidence Contract** — zeitlich begrenzte, widerrufbare Behauptungen:
`Was wurde verifiziert? · Wann? · Gegen welche Policy? · Wie lange gültig? · Wo liegt der Beweis?`

**Capability Contract** — der **einzige bewusst leaky** Contract:
`engine-spezifische Fähigkeiten: pgvector · PostGIS · logical replication · ...`

### 4.2 Portabilitäts-Versprechen (ehrlich, drei Ebenen)

```text
Lifecycle portability          YES   Provision, Observe, Backup, Restore,
                                     Rotate, Upgrade, Delete
Operational semantics          PARTLY  RPO/RTO, HA-Modell, Maintenance-Policy,
                                     Isolation, Backup-Residency
Database feature portability    NO   Extensions, SQL-Dialekt, Replikations-Features,
                                     Tuning, engine-spezifische Capabilities
```

Der Contract sagt **nicht** „Alle Datenbanken sind austauschbar", sondern „Database
Services werden über ein konsistentes OpenKubes-Betriebsmodell verwaltet". Ein externer
PostgreSQL-Service könnte später dasselbe Lifecycle-Interface erfüllen, ohne
Feature-Parität mit CNPG vorzugeben.

**Leitprinzip:** *Don't pretend the abstraction doesn't leak. Define where it is allowed
to leak.* Der einzige erlaubte Leak-Ort ist der Capability Contract.

## 5. Evidence- und Readiness-Modell

Evidence ist eine **zeitlich begrenzte Behauptung**, kein Boolean:

```yaml
status:
  evidence:
    restore:
      state: Valid            # Pending | Valid | Stale | Failed
      observedAt: 2026-08-14T01:34:00Z
      validUntil: 2026-08-15T01:34:00Z
      evidenceRef: ...
```

**`Stale` ≠ `Failed`** — eine wichtige Unterscheidung:
`Failed` = wir haben einen **Gegenbeweis**. `Stale` = wir haben **derzeit keinen
ausreichend frischen Beweis**. `Pending`/`Unknown` (mit `reason`, z.B.
`AwaitingFirstBackup` / `VerificationPending`) ist **Teil des Modells**, kein Sonderfall
außerhalb davon — damit ist der Bootstrap-Zustand (§5.3) formal abgedeckt. Bei späterer
Nutzung von Kubernetes Conditions entspricht das `status: Unknown` + klarem `reason`.

### 5.1 Vier Conditions — als Set, nicht als Pipeline

Wichtig: Die Conditions bilden **kein lineares Chain**, sondern ein flaches, per Policy
ausgewertetes Set. Nur `RecoveryAssured` hängt echt an `ProtectionReady`.
`CapabilityConformant` ist eine Provisioning-/Betriebstatsache und **unabhängig** von
Backup/Restore — es linear darunter zu hängen würde die pgvector-Bestätigung fälschlich
hinter den Backup-Zyklus deadlocken.

```text
OperationalReady      (current sensors)
ProtectionReady       (backup/WAL freshness)
RecoveryAssured       (restore evidence + TTL; hängt an ProtectionReady)
CapabilityConformant  (requested engine capabilities; unabhängig)
        │
        ▼
DatabaseServiceReady  = reine Policy-Auswertung der obigen Evidence,
                        erzeugt keine eigene technische Wahrheit
```

### 5.2 Policy je Klasse

```text
development                      production
───────────                      ──────────
OperationalReady     required    OperationalReady     required
ProtectionReady      optional    ProtectionReady      required
RecoveryAssured      maxAge 7d    RecoveryAssured      maxAge 24h
                                 CapabilityConformant required
```

Damit kann der Service echt von `Ready → NotReady` **zurückfallen**, wenn eine
zugesicherte Evidence veraltet — eines der stärksten Elemente des Entwurfs.

### 5.3 Bootstrap-Reihenfolge (State-Machine-Detail)

`RecoveryAssured` hängt an `ProtectionReady`; zum Provisioning-Zeitpunkt (t=0) existiert
noch kein Backup. Daher: `RecoveryAssured` startet als `Pending/Unknown`, die **erste**
Verifikation läuft nach dem **ersten erfolgreichen Backup**, und die `maxAge`-Policy
greift erst **ab** der ersten erfolgreichen Verifikation. Andernfalls blockiert das
Evidence-Gate genau das Provisioning, das es schützen soll.

### 5.4 Restore-Verifikation — was `RecoveryAssured` ehrlich beweist

CNPG-Recovery/PITR erzeugt einen **neuen** Cluster aus Base-Backup + WAL (kein
„Restore-Knopf" auf dem bestehenden Cluster). Das erlaubt eine echte, isolierte
Verifikation:

```text
BackupAvailable → scheduled/triggered verification → disposable recovery environment
→ structural integrity checks → RestoreVerified{timestamp, backupID, recoveryTarget,
  duration, evidenceRef}
```

Scope-Ehrlichkeit für v1: `RecoveryAssured=Valid` beweist, dass das Backup zu einem
laufenden Cluster auf ein gewähltes Recovery-Target **strukturell** restaurierbar ist
(Katalog-Konsistenz, erwartete Relations vorhanden). **Anwendungssemantische**
Konsistenz ist Sache des jeweiligen forcing consumers, nicht der Plattform — sonst
überzeichnet das Flag.

**Invariante (implementierungs-neutral):**

> A recovery-verification environment MUST have read-only access to the backup source
> under test and MUST write any new backup/WAL artifacts to an isolated destination.

Als CNPG-spezifische **Spike-Annahme** (nicht Architekturregel): Für den gewählten
Barman-/CNPG-Mechanismus die erforderliche *destination/server identity isolation*
validieren. Hinweis: In aktuellen CNPG-Versionen ist das eingebaute
`.spec.backup.barmanObjectStore` zugunsten der CNPG-I-/plugin-basierten Backup-/WAL-
Architektur deprecated — die konkrete Isolationsmechanik ist daher versionsabhängig und
gehört in den Spike, nicht in die Invariante.

## 6. Contract-Feldskizze (`Database`, orthogonal geschnitten)

`class` als überladenes Feld wird vermieden; HA, Performance, Protection etc. sind
orthogonale Dimensionen. Convenience-**Profile** sind nur versionierte Bundles dieser
Dimensionen (keine doppelte Wahrheit).

```yaml
apiVersion: platform.openkubes.org/v1alpha1
kind: Database
spec:
  engine:
    name: postgresql
    majorVersion: 18
    capabilities:                       # der bewusst-leaky Teil
      - name: postgresql.extension.pgvector
        versionPolicy: platform         # Version von der Plattform gesteuert

  performance:
    class: standard
  availability:
    mode: ha                            # single | ha — technische Availability-Semantik (z.B. ≥N replicas, anti-affinity)
  connectivity:
    pooling: { enabled: true, mode: transaction }   # CNPG native Pooler/PgBouncer
  protection:
    policyRef: standard
  maintenance:
    upgradePolicy: controlled
    windowRef: saturday-night
    majorVersionStrategy: blueGreen
  isolation:
    class: dedicated                    # später: shared | dedicated-instance | dedicated-node
  dataPolicyRef: eu-production          # Residency als Policy, nicht als deklaratives Flag
  policyRefs: [...]
```

Profil-Beispiel:

```text
profile: production-standard
  = performance.standard + availability.mode.ha + protection.production
    + isolation.dedicated + maintenance.controlled
```

### 6.1 Residency als Policy + Evidence (nicht als deklaratives Flag)

`residency: eu` allein beweist nichts. Stattdessen `dataPolicyRef`, das
`primaryDataRegions / backupRegions / encryption / retention / allowed providers`
definiert; die Plattform beweist Konformität:

```text
Requested policy → Resolved storage location → Observed backup destination
→ PolicyConformant = True
```

### 6.2 Credential Rotation — die Semantik muss im Contract stehen

Rotation eines App-Secrets droppt keine bestehenden Sessions; Apps, die das Secret nur
beim Boot lesen, sehen die Rotation nie. Der Lifecycle Contract muss **zusichern**, ob
OpenKubes zero-downtime-Rotation garantiert (Dual-Secret + Grace-Period) oder nur „neues
Secret publiziert, App verantwortet Reconnect". Beides ist vertretbar — aber es muss
festgeschrieben sein, weil es am Vault-/Secret-Modell hängt.

### 6.3 Capability × Upgrade × Evidence sind gekoppelt

`CapabilityConformant` ist gleichzeitig Capability- **und** Evidence-Concern. Ein
Major-Upgrade kann eine Extension still brechen — die Capability muss daher **nach jedem
Upgrade neu bewiesen** werden. Die vier Contracts sind sauber benannt, an dieser Stelle
aber bewusst gekoppelt.

### 6.4 Capability-Allowlist (governed leak)

Kein freies `extensions: [irgendein-beliebiges-so]`. Stattdessen ein Katalog:

```text
Requested capability → OpenKubes Capability Catalog:
  supported PG versions · approved image · extension version · provenance
  · backup compatibility · upgrade compatibility · conformance tests → Accepted
```

CNPG passt technisch (kontrollierte Images, `ImageCatalog`/`ClusterImageCatalog`) — damit
wird pgvector eine **plattformseitig zugesicherte Capability**, kein SQL-Befehl einer App.

> **Framing-Schutz:** pgvector ist im Spike der *forcing capability consumer* — er setzt
> das Extension-/Capability-Modell unter Druck. Er ist **nicht zwingend die erste
> OpenKubes-Produktdatenbank**. Diese Unterscheidung verhindert, dass der Spike
> unbeabsichtigt zu einem AI-/Postgres-Implementierungsprojekt wird, statt die
> Architekturgrenze zu beweisen.

## 7. Automation-Grenze: automate the mechanics, keep authority explicit

`Automation != autonomous change`. Besonders bei Major-Upgrades: CNPG kennt mehrere
Verfahren (u.a. Offline-In-Place sowie Offline-/Online-Import) mit unterschiedlichem
Downtime-/Rollback-Profil. **Rollback behaviour and operator intervention requirements
differ by upgrade strategy and MUST be validated for the selected CNPG version.**

```text
OpenKubes automates              Operator controls
──────────────────               ─────────────────
preflight                        maintenance policy
compatibility checks             change approval
backup verification              execution window
restore rehearsal                risk acceptance
upgrade plan
execution mechanics
post-upgrade verification
rollback mechanics where possible
```

Prinzip: *Automate the facts and mechanics. Keep consequential authority explicit.*

## 8. Warum ein eigener Contract statt Everest/KubeBlocks? (bewusster Trade-off)

Everest/KubeBlocks liefern bereits DBaaS-UX und Multi-Engine. Ein eigener Contract
darauf bedeutet zusätzlichen Bau- und Wartungsaufwand. Die explizite Antwort ist **nicht**
„weil wir es besser können", sondern:

> *OpenKubes deliberately owns the platform contract, service objectives and evidence
> model while delegating database mechanics to replaceable implementations.*

Preis: zusätzlicher Aufwand. Gewinn: OpenKubes besitzt seine Architekturgrenze selbst.
Everest/KubeBlocks bleiben **Implementierungskandidaten hinter dem Contract**, nicht der
Contract selbst.

```text
Application → OpenKubes DB Contract → { CNPG | Everest | KubeBlocks | Cloud DB }
```

## 9. Non-Goals für v1 (explizit)

```text
Non-goals for v1
─────────────────────────────────────────
Multi-engine abstraction
Feature portability between DB engines
Application-semantic restore validation
Commercial SLA / 24x7 accountability
Arbitrary PostgreSQL extensions
Unbounded user-provided DB images
Shared multi-tenant database clusters
Automatic execution of every major upgrade
Everest/KubeBlocks replacement
Premature choice of Crossplane/controller
```

## 10. Claims we intentionally do not make

Dieser Abschnitt schützt das Dokument gegen spätere Überinterpretation. OpenKubes
behauptet ausdrücklich **nicht**:

- OpenKubes does **not** claim database-engine **feature portability**.
- OpenKubes does **not** itself provide a commercial **SLA**.
- `RestoreVerified` does **not** establish **application-semantic** consistency.
- A **declared policy** is **not** evidence of policy conformance.
- **Automation** does **not** imply **autonomous authority** for consequential changes.

## 11. Zu entscheidende Semantik (Acceptance-relevant)

Die folgenden vier Punkte sind **keine Implementierungsdetails**, sondern **Semantik, die
der Spike entscheiden muss**, bevor der ADR `Accepted` werden kann.

**11.1 Bootstrap semantics.** `RecoveryAssured = Pending/Unknown` darf das
Initial-Provisioning **nicht** blockieren. Der Spike muss bestimmen, *wann*
Protection-Evidence erstmals verpflichtend wird und wie Grace-Period/Freshness
funktionieren. (Detail: §5.3)

**11.2 Meaning of restore evidence.** `RecoveryAssured = Valid` darf nur behaupten, was
tatsächlich bewiesen wurde: *technisch restaurierbar plus definierte strukturelle
Integrität*. Keine implizite Behauptung anwendungssemantischer Korrektheit. (`RestoreVerified`
ist höchstens der Name des darunterliegenden Evidence-Artefakts/Ereignisses, das
`RecoveryAssured` speist — nicht die Condition selbst: `restore verification evidence →
RecoveryAssured`.) (Detail: §5.4)

**11.3 Recovery isolation invariant.** Als **harte, implementierungs-neutrale Invariante**:

> **A recovery-verification environment MUST have read-only access to the backup source
> under test and MUST write any new backup/WAL artifacts to an isolated destination.**
> (Kurzform: restore verification MUST be unable to mutate the backup source it is verifying.)

Die CNPG-spezifische Isolationsmechanik ist Spike-Annahme, nicht Architekturregel. (Detail: §5.4)

**11.4 Credential lifecycle semantics.** OpenKubes verspricht v1 **nicht** automatisch
„zero downtime". Der Spike entscheidet, was garantiert wird:

```text
Secret rotation
     ├── credential generated/rotated
     ├── new consumer material published
     ├── overlap/grace semantics?
     ├── old credential revoked when?
     └── application reconnect responsibility where?
```

(Detail: §6.2)

## 12. Offene Fragen — bewusst dem Spike überlassen

- Ob das Ergebnis `ok-dbaas` heißt, welche API-Ressource entsteht.
- Composition-/Implementierungsmechanismus: **Crossplane ist Implementierungskandidat,
  keine Prämisse des Contracts.** Erst im Spike prüfen, ob `???` = Crossplane, ein
  dünner Controller, Admission + Manifeste oder etwas anderes ist. Falls Crossplane zu
  dem Zeitpunkt bereits verbindlicher OpenKubes-Mechanismus ist, gewinnt es durch
  Konsistenz.

```text
OpenKubes Database Contract → ??? Composition → CloudNativePG
```

## 13. Path to Acceptance — Architektur-Spike

Dieser ADR ist **Proposed**. Der Spike ist der explizite Pfad zu `Accepted` (und der
Auslöser für den Zwischenstatus `Draft — pending acceptance evidence`, sobald er als Gate
aufgesetzt ist):

```text
Proposed ADR
│  ├── hält die Architekturgrenze fest
│  ├── dokumentiert die konvergierten Prinzipien
│  ├── benennt offene Entscheidungsfragen (§11, §12)
│  └── definiert, welche Evidence für Accepted nötig ist
▼  Spike established as acceptance gate
Draft — pending acceptance evidence
▼
Architecture Spike
│  ├── PostgreSQL        → Lifecycle forcing consumer
│  ├── CNPG              → implementation forcing consumer
│  ├── pgvector          → capability-boundary forcing consumer
│  ├── restore drill     → evidence forcing consumer
│  └── major upgrade /
│      credential rotation → Day-2 forcing consumers
▼
Evidence + Decision
▼
ADR  →  Accepted | revised | rejected
```

**Acceptance-Kriterium:** Der ADR wird `Accepted`, wenn der Spike für §11.1–§11.4 je eine
entschiedene Semantik liefert, die `???`-Composition-Frage (§12) begründet auflöst und die
CNPG-Annahmen (Kopfhinweis) gegen die Zielversion bestätigt.

### Spike-Definition

**Titel:** *Define the OpenKubes Database Platform Contracts and validate
PostgreSQL/CloudNativePG plus pgvector as forcing consumers.*

**Zentrale Frage:** *Can OpenKubes automate the hard database Day-2 lifecycle and produce
fresh, revocable evidence of its service objectives while keeping accountability outside
the platform and engine-specific semantics explicit?*

**Sub-Fragen:**

```text
1. PORTABILITY  Welche Semantik ist portabler Plattform-Contract,
                welche muss explizit engine-spezifisch bleiben?
2. EVIDENCE     Welche Claims brauchen Evidence, wie wird sie erzeugt,
                wann läuft sie ab?
3. AUTOMATION   Welche Day-2-Mechanik automatisiert OpenKubes,
   BOUNDARY      welche folgenschweren Entscheidungen bleibt Operator-kontrolliert?
```

**Forcing consumers — jeder setzt eine Architekturannahme unter Druck:**

```text
PostgreSQL      → forces lifecycle model
CloudNativePG   → forces implementation viability
pgvector        → forces capability/extension model
restore drill   → forces evidence freshness model
major upgrade   → forces automation/authority boundary
```

Weder `ok-dbaas`, noch eine `Database`-CRD, noch Crossplane werden als Ergebnis
vorausgesetzt. Sagt der Spike am Ende, dass genau diese drei sinnvoll sind: hervorragend —
dann sind sie **Resultat** der Architekturarbeit, nicht ihre Ausgangsannahme.

---

## Referenzen (Design-Grundlage, im Spike gegen Zielversion zu bestätigen)

- CloudNativePG — Operator Capability Levels, Recovery/PITR, Monitoring, Pooler,
  ImageCatalog, PostgreSQL Major Upgrades (cloudnative-pg.io).
- Crossplane — Compositions / Composite Resources (docs.crossplane.io).
- pgvector — PostgreSQL vector similarity extension, PG 13+ (github.com/pgvector/pgvector).
- Percona Everest / KubeBlocks — Multi-Engine-Kubernetes-Database-Plattformen
  (Implementierungskandidaten).
