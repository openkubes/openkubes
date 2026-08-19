# ADR-Platform-032: OpenKubes DBaaS — Database Platform Contracts (PostgreSQL Reference)

- **Status:** **Accepted — architectural** (2026-08-17). The four contracts of §4.1 are decided and
  the §13 criterion is met *as an architecture spike*: §11.1–§11.4 resolved, §12 resolved, the CNPG
  assumptions checked against 1.30.0, and a restore drill genuinely **executed** on ok-robotics.
  **This is explicitly not delivered-capability acceptance**, and the distinction is load-bearing
  rather than cautious:
  - `ProtectionReady=Valid` is reachable only under a **narrowed** RPO claim (§11.1, §10): WAL
    age/backlog is not observable, so v1 uses `ContinuousArchiving=True` plus backup-window
    freshness and explicitly does **not** provide an RPO bound.
  - `RecoveryAssured=Valid` requires an **admitted** `RestoreVerified` artifact (§11.2). The drill's
    own artifact predates that typed contract and is **not admissible** under it; it stands as the
    historical record of the run, not as evidence satisfying v1.
  - Capability delivery is unevidenced: no functional probe feeds `CapabilityConformant`, and
    extension delivery additionally needs the Kubernetes `ImageVolume` feature gate, which was
    disabled on the drill cluster (note on sources, finding 1).
  The contracts, the evidence semantics and the drill method are accepted. The capability that
  implements them is **installed on ok-mgmt as of 2026-08-18** — authority policy (compiled by the
  API server with no CEL type-check warnings), `RestoreVerified` CRD, RBAC, the `ok-robotics`
  provider-kubernetes ProviderConfig, the XRD (Established, Offered) and the Composition. Installing
  it required a second, explicit acknowledgement (`ACCEPT_PROTOTYPE_LIMITS=yes`) precisely so a
  successful install cannot be read as closing the bounds below: it does not.
  Delivered-capability acceptance still needs WAL-freshness observability, an admissible
  `RestoreVerified` artifact produced under the typed API, and a functional capability probe.
- **Datum:** 2026-08-14, semantics decided 2026-08-17
- **Kontext:** OpenKubes Kubernetes Platform (OKE) / OpenKubes AI
- **Betrifft:** Data-Capability der OpenKubes-Plattform (`ok-dbaas`, Arbeitstitel)
- **Nummerierung:** Abgelegt als `architecture/decisions/ADR-Platform-032-openkubes-dbaas.md` (nächste freie Nummer nach `ADR-Platform-031`), konsistent mit der bestehenden Plattform-Serie.

> **Note on sources — schema surfaces checked against CNPG 1.30.0 (2026-08-17).** The API-shape
> assumptions were checked against the **installed CRD schemas** of `clusters.postgresql.cnpg.io`,
> `poolers`, `clusterimagecatalogs` and `backups` on a live 1.30.0 operator. **That confirms those
> schema surfaces only.** It does not verify controller or runtime behaviour, the installed
> `ImageCatalog` CRD (not inspected), major-upgrade execution, recovery behaviour, or any Barman
> Cloud Plugin API. Where a statement below rests on documentation rather than on the inspected
> schema, it says so.
>
> - **PITR** appears in the schema only as `bootstrap.recovery` with `recoveryTarget` (`backupID`,
>   `targetTime`, `targetLSN`, `targetXID`, `targetImmediate`, …) — i.e. recovery is exposed as a
>   *bootstrap* method, with no recovery field on a running cluster. That a new cluster is
>   *always* the result is CNPG's documented behaviour; the schema shows the shape, not the
>   behaviour. §5.4 and §11.3 rest on this.
> - **`Pooler`** (`type: rw|ro|r`, `pgbouncer.poolMode: session|transaction`) and
>   **`ClusterImageCatalog`** exist as assumed. `ImageCatalog` was not inspected.
> - **Major-upgrade procedures** exist as assumed — in-place by moving `imageCatalogRef.major` or
>   `imageName`, import-based via `bootstrap.initdb.import`. **Correction to a tempting
>   shortcut:** `primaryUpdateStrategy: supervised` and `primaryUpdateMethod: switchover|restart`
>   govern updating the *primary during a rolling update*; they are **not** the approval gate for
>   an offline in-place major upgrade, which is triggered by selecting a higher-major image and
>   runs its own shutdown/`pg_upgrade` path. §7's authority boundary must therefore be enforced
>   **before** `imageName`/`imageCatalogRef.major` changes, by the platform's own approval
>   workflow — CNPG has no native gate that does this for us.
>
> Three findings go beyond confirmation and are worked into the normative text:
>
> 1. **Extensions are their own images — and delivery needs a Kubernetes prerequisite we did not
>    have.** `Cluster.spec.postgresql.extensions[]` (with `image`, `extension_control_path`,
>    `dynamic_library_path`) and `ClusterImageCatalog.images[].extensions` do map §6.4 onto a native
>    surface, so the capability allowlist can be a catalogued image reference rather than an SQL
>    statement an application issues. **Delivery was not demonstrated, and the cause lies outside
>    CNPG and outside this contract.** Measured on ok-robotics (2026-08-17, k8s v1.34.1):
>    `CREATE EXTENSION vector` failed with *"extension vector is not available"*, the `postgres`
>    container had **no `/extensions` mount**, and the pod spec contained **no image-type volume at
>    all** — while `kubernetes_feature_enabled{name="ImageVolume",stage="BETA"}` reported **0**.
>    CNPG's declarative extensions are built on image volumes (KEP-4639), so with that gate disabled
>    no volume can exist. Reproduced on a **freshly created** cluster and again with an explicit
>    `postgresql.extensions[].image.reference`, which rules out both a rolling-restart effect and a
>    manifest-shape error. **Enabling the `ImageVolume` feature gate is necessary but not
>    sufficient, and on this platform extension delivery does not work at all.** Re-measured
>    2026-08-19 with the gate enabled: on ok-robotics (Talos v1.9.5, containerd 2.0.3, k8s v1.34.1,
>    gate beta-enabled, metric reporting **1**) the pod receives a real image volume and the
>    extension image pulls in 1.981s, but the container cannot be created —
>    `failed to apply OCI options: failed to mkdir "": mkdir : no such file or directory` — and the
>    instance never starts. The identical error, character for character, occurs on a second cluster
>    (Talos v1.9.6, containerd 2.0.5, k8s v1.36.2) where `ImageVolume` is **GA and enabled by
>    default**. The failure is therefore invariant across two Talos versions, two containerd
>    versions, two Kubernetes versions and both gate stages, which points at the Talos containerd
>    configuration rather than any of those variables; it is **not root-caused**. The cluster
>    requirement is consequently *a node runtime that can mount image volumes* **and** the gate —
>    not the gate alone. **Operationally: enabling the gate on ok-robotics took the database down**
>    (~8 minutes; the instance could not start until the gate was reverted), so "just enable the
>    gate" is not a safe instruction.
>
>    **pgvector itself is viable — through a different mechanism than this ADR chose.** Delivered by
>    a bundled image (`ghcr.io/cloudnative-pg/postgresql:18.6-standard-trixie`, whose `standard`
>    variant ships `vector.control`), `CREATE EXTENSION vector` succeeds and reports pgvector
>    **0.8.6**, with L2 distances computed correctly (`sqrt(27)` for `'[4,5,6]'` against
>    `'[1,2,3]'`) — no image volume, no gate, no machine-config change. The same probe script
>    returned `Failed/RequestedCapabilityAbsent` against the composed Database in the same minute.
>    The tradeoff must not get lost: `standard` bundles a **fixed** extension set, strictly weaker
>    than §6.4's per-extension allowlist for approved-image, version and provenance governance. So
>    the honest statement is that the capability is deliverable, while **this ADR's
>    catalogued-per-extension-image model is unvalidated on Talos**.
>
>    **The load-bearing lesson is about evidence, not about pgvector.** CNPG reported the extension
>    as configured throughout: `status.pgDataImageInfo.extensions` listed
>    `{name: vector, image: {reference: …}}` on a cluster where the extension could not be created.
>    A declaration echoed back in status is **not** evidence of function, so `CapabilityConformant`
>    MUST derive from a functional probe — `CREATE EXTENSION`, `pg_available_extensions`, or an
>    actual use of the capability — never from the operator restating what it was asked for. §6.3
>    already requires re-proving capability after every upgrade; this is that same rule applied at
>    provisioning time. The v1 Composition is correct but incomplete here: it maps the status echo to
>    `Pending/CapabilityProbePending` rather than to `Valid`, and no probe yet feeds it, so
>    `CapabilityConformant=Valid` is unreachable for a requested capability. That, not the gate, is
>    what puts extension-requesting consumers out of v1 scope.
> 2. **The obvious freshness fields are deprecated, and the obvious replacement is not enough.**
>    `Cluster.status.lastSuccessfulBackup`, `firstRecoverabilityPoint`, `lastFailedBackup` and
>    both `*ByMethod` variants are deprecated in 1.30 and are **not set for backup plugins**, so
>    on the chosen CNPG-I path (§12) code reading them is wrong: it works on the deprecated path
>    and silently reports nothing on the supported one. But a completed `Backup` CR is not the
>    replacement either — it is an **execution record**, not proof that the backup is still
>    available. Plugin retention can prune the object-store backup while the CR remains, and
>    garbage-collecting the CR does not mean the object-store data is gone. `ProtectionReady`
>    therefore needs separate signals, per §11.1.
> 3. **Isolation is *representable* by construction — not thereby proven.**
>    `bootstrap.recovery.source` refers to an `externalClusters[]` entry that carries its **own**
>    object store, separate from the recovery cluster's `spec.backup`/`spec.plugins`. So §11.3 can
>    be expressed as separate credentials and destinations rather than as a rule nobody can
>    check. What the schema cannot establish is that the source credential is actually read-only:
>    that is an IAM/runtime fact and needs the evidence §11.3 demands. Sharp edge: the source name doubles as the server
>    directory under `destinationPath`, so a mistyped name silently reads a *different* server's
>    WAL instead of failing — and on the plugin path that directory comes from the plugin's
>    `serverName`, which is overrideable, so isolation checks must compare **resolved effective
>    values** rather than the `source` name.

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

**Completed by the spike (§11.1): the two deadline attributes, and the state mapping.** Both are
**attributes of the protection class** selected by `protection.policyRef` — they are *not*
claimant fields, and a claim cannot set them:

```text
attribute                       development   production   clock origin
──────────────────────────────  ───────────   ──────────   ─────────────────────────────────────
protection.gracePeriod             72h          24h        later of: cluster first Ready, and
                                                           first scheduled backup due time
                                                           + permitted lateness
protection.initialVerification-     14d          72h       first successful backup
  Deadline
RecoveryAssured.maxAge              7d           24h       first successful verification
```

`gracePeriod` bounds *how long a database may exist with no first backup*; `maxAge` bounds *how
old restore evidence may be*. They are independent, and the fact that `production` sets both to
24h is a coincidence of defaults, not one setting.

**Evidence state → condition status.** Evidence state is the observed fact; the condition is the
policy verdict over it, so the mapping must be stated or the two vocabularies drift:

```text
evidence state   condition status   note
──────────────   ────────────────   ────────────────────────────────────────────────
Valid            True               within the class's freshness bound
Failed           False              counter-proof exists
Stale            False              was Valid, now beyond maxAge, and still present —
                                    required class only; where the condition is
                                    `optional`, Stale keeps DatabaseServiceReady
                                    unaffected but stays visible. If the artifact is
                                    positively gone, the state is Failed, not Stale (§11.1)
Pending          Unknown            never yet proven; carries a reason
Unknown          Unknown            cannot observe; carries a reason
```

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
→ selected schema/capability conformance probes → RestoreVerified{…}
```

Scope honesty for v1: `RecoveryAssured=Valid` proves that the backup was restorable to a running
cluster at a recovery target, and that the **selected schema and capability conformance probes**
passed. **Application-semantic** consistency is the respective forcing consumer's concern, not the
platform's — claiming it would overstate the flag.

> **Narrowed by the spike (§11.2).** This section previously said "structural integrity checks"
> and "strukturell restaurierbar (Katalog-Konsistenz)". Both were too strong: catalogue presence
> proves that a relation is listed, not that its pages are readable, that its indexes are
> consistent, that TOAST data can be read, or that an extension's binary loads. §11.2 is the
> normative wording; the exact probe set is a property of the check profile, and the artifact's
> field list also lives there.

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
apiVersion: platform.openkubes.ai/v1alpha1   # group per §12; the platform uses .ai, not .org
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
    policyRef: production               # v1 enum per §12: development | production — the classes
                                        # §5.2 actually defines. The earlier sketch value
                                        # "standard" named no class and is corrected here; note
                                        # performance.class DOES have a "standard" value, which is
                                        # how the two got conflated.
  maintenance:
    upgradePolicy: controlled
    windowRef: saturday-night
    majorVersionStrategy: blueGreen
  isolation:
    class: dedicated                    # später: shared | dedicated-instance | dedicated-node
  dataPolicyRef: eu-production          # Residency als Policy, nicht als deklaratives Flag
                                        # (per §12 NOT implemented in v1 — no policy resolution
                                        #  mechanism exists yet; §6.1 stays design intent)
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
```

This list is deliberately the one OK-145 defined, minus one entry. "Premature choice of
Crossplane/controller" has been **removed** rather than annotated: §12 decided that question on the
spike's evidence, so listing its avoidance as a v1 non-goal would contradict the decision instead of
qualifying it.

## 10. Claims we intentionally do not make

Dieser Abschnitt schützt das Dokument gegen spätere Überinterpretation. OpenKubes
behauptet ausdrücklich **nicht**:

- OpenKubes does **not** claim database-engine **feature portability**.
- OpenKubes does **not** itself provide a commercial **SLA**.
- `RestoreVerified` does **not** establish **application-semantic** consistency.
- A **declared policy** is **not** evidence of policy conformance.
- **Automation** does **not** imply **autonomous authority** for consequential changes.
- **`ProtectionReady=Valid` is not an RPO bound in v1.** It combines execution evidence, current
  catalogue availability and `ContinuousArchiving=True`. It does **not** measure WAL lag, because no
  such observation is available to the platform yet (§11.1). A consumer needing a bounded RPO must
  not read this condition as providing one.

## 11. Decided semantics (acceptance-relevant)

These four points are not implementation details but the semantics the spike had to decide. They
are **decided** here. Each carries its reasoning, because a decision recorded without its reason
reads as arbitrary six months later — and two of these were decided *against* the first answer
the spike proposed.

**11.1 Bootstrap semantics — decided.** `RecoveryAssured = Unknown` does not gate initial
provisioning.

- At t=0 both protection conditions start as `Unknown` with an explicit reason:
  `ProtectionReady=Unknown/AwaitingFirstBackup`, `RecoveryAssured=Unknown/VerificationPending`.
- `DatabaseServiceReady` is pure policy evaluation (§5.1): in class `development` it MAY be
  `True` while both are `Unknown`; in class `production` it MUST NOT be, until
  `ProtectionReady=True` and `RecoveryAssured=Valid` have each been observed once.
- `protection.gracePeriod` is an **attribute of the protection class**, not a claimant field, and
  its per-class values and clock origin are defined in §5.2. Its clock origin is the **later** of
  two events: the underlying cluster first reporting Ready, and the first scheduled backup's due
  time plus permitted lateness. Both halves are needed — a cluster that never came up has no
  backup obligation yet, and a schedule whose first window has not arrived cannot be overdue.
  Do not read its `production` default as the same quantity as §5.2's `RecoveryAssured maxAge`:
  this one bounds *how long a database may exist without a first backup*, the other *how old
  restore evidence may be*.
- When the grace period elapses with no successful backup, `ProtectionReady` becomes
  **`False/BackupOverdue`**, not `Stale`: the schedule had its window and produced nothing,
  which is a counter-proof, and §5 reserves `Failed` for exactly that. Two conditions keep this
  from being a category error:
  - The deadline is **schedule-aware** — first due time plus permitted start/runtime lateness,
    not simply `clusterReadyAt + 24h`.
  - **Being unable to observe is not a counter-proof.** An API outage, missing permissions, a
    missing collection mechanism, or lost backup history yields
    `Unknown/ObservationUnavailable`, never `False`.

  ```text
  deadline conclusively missed        → False/BackupOverdue
  previous success now too old        → Stale
  observation incomplete/unavailable  → Unknown
  ```

- **`ProtectionReady` is computed from more than one signal**, because no single one carries the
  claim (see head-note finding 2). The `Backup` CR is a **historical execution record** and the
  origin of `backupId` — not an immutable one: its status changes while the backup runs and the
  object can be deleted, and this ADR establishes no immutability guarantee for it. **Current
  availability** comes from the plugin's last-available-backup
  and first-recoverability-point signals, or an equivalent authenticated Barman catalog query;
  **RPO health** — narrowed for v1, deliberately (2026-08-17). The original wording required
  "continuous-archiving state plus WAL age/backlog". The second half is **not observable**: the
  Barman Cloud Plugin v0.14.0 publishes no WAL age or backlog in any status field, and the
  Composition can read Kubernetes resources only, not the operator's metrics endpoint. Rather than
  invent a proxy or leave `ProtectionReady=Valid` permanently unreachable, v1's archiving signal is
  `Cluster.status.conditions[ContinuousArchiving]` alone, combined with backup-window freshness.
  **What that costs must be stated plainly: v1's `ProtectionReady` is therefore NOT an RPO bound.**
  `ContinuousArchiving=True` means archiving is not currently failing; it says nothing about how far
  behind the archive is, so a slow or stalled-but-not-failed archiver satisfies it. The full claim
  needs a WAL-age observation published as a typed resource the Composition can select — the same
  pattern as `RestoreVerified` in §11.2 — and is deferred with the other bounds in §13.
  Platform-persisted
  evidence is historical audit only and never establishes current availability by itself. Note
  that CNPG's `backupOwnerReference` (default `none`) governs CR garbage collection when a
  `ScheduledBackup` or `Cluster` is deleted; it is not a source of truth about object-store
  retention. If the current-availability signal cannot be observed, the condition is
  `Unknown/BackupAvailabilityUnproven` — not `False`, and certainly not `True`.
- **Unavailable is not the same as unproven, and it outranks `Stale`.** The three cases must stay
  distinct, and the third is the one that is easy to get wrong:

  ```text
  no availability signal readable          → Unknown/BackupAvailabilityUnproven
  prior Valid, TTL elapsed, still there    → Stale/BackupEvidenceExpired
  availability says the backup is GONE     → Failed/BackupUnavailable
  ```

  The third case takes precedence over `Stale` even when prior evidence exists and its TTL has
  expired. Reporting `Stale` there would say "our proof is old" about a backup we have positive
  evidence no longer exists — which is a counter-proof, and §5 reserves `Failed` for counter-proof.
  A pruned backup reported as merely stale is the most dangerous reading in this whole model,
  because staleness invites waiting and absence demands acting.
- The `RecoveryAssured.maxAge` clock starts at the **first successful verification** (§5.3), so a
  `production` database reaches Ready only after a completed restore drill. That is intended, not
  a side effect. So that "never verified" cannot sit as `Unknown` indefinitely, a
  `protection.initialVerificationDeadline` also applies: if it elapses with no first
  verification, `RecoveryAssured` becomes `False/VerificationOverdue`. Without that second clock
  the `maxAge` policy of §5.2 would be **unenforced** before the first verification rather than
  unsatisfiable — a liveness hole, not a contradictory constraint: a database could sit forever
  at `Unknown` and never violate a max-age bound whose clock had not started. Both attributes are
  defined per class in §5.2, including their clock origins.
- **State-machine invariant:** `Stale` is reachable **only** from a prior `Valid`. Nothing may
  report `Stale` that has never been `Valid` — otherwise "no proof yet" and "the proof went out
  of date" collapse into one state, and that distinction is the whole point of §5.

**11.2 Meaning of restore evidence — decided.** `RecoveryAssured = Valid` asserts exactly this
and nothing beyond it:

> From the backup identified by `backupId`, the platform created a **new** PostgreSQL cluster
> that left the **actually reached** recovery target (timeline/LSN) and arrived at a connectable
> state outside recovery mode, and the **selected schema and capability conformance probes**
> passed.

The wording is deliberately weaker than "structural integrity". A relation name plus `relkind`
proves **catalogue presence**, not readability: it says nothing about whether the relation's pages
are readable, whether indexes are internally consistent, whether TOAST data can be read, or
whether an extension's binary loads and its functions execute. `pg_extension.extversion` likewise
proves installed metadata, not working capability. Going beyond catalogue presence means putting
real reads, representative index scans or `pg_amcheck`, and extension smoke tests into the check
profile — a question of the profile, not of the condition. The second half of the sentence carries
its own weight: the **requested** recovery target is not the **reached** one, and the artifact
records what was reached.

Explicitly **not** asserted (extending §10): no row-level correctness, no application-semantic
consistency, no referential integrity of application data, no statement about *other* backups
(earlier or later), no statement that the application identity, network path or a `Pooler` can
connect, and **no RTO conformance**. Duration is recorded in the artifact, but RTO is a separate
Service Objective claim: conflating the two would let a six-hour restore report a fifteen-minute
objective as met.

Naming: the artifact/event is `RestoreVerified`, the condition is `RecoveryAssured`
(`restore verification evidence → RecoveryAssured`). Artifact fields:

```text
identity of what was restored   backupId, backupRef.uid, sourceSystemIdentifier,
                                sourceClusterRef.uid
where it came from              resolved endpoint, bucket, pathPrefix, serverName
                                (the resolved values, not the requested ones — §11.3)
what was asked and reached      recoveryTarget.requested, recoveryTarget.reached{timelineId, lsn}
timing                          startedAt, completedAt, duration
what was checked                checks[], checkProfileDigest, manifestDigest
isolation                       effectivePolicyResult, writeDenialProbeResult
who verified it, with what      verifierVersion, cnpgVersion, pluginIdentity, pluginVersion
pointer                         evidenceRef
```

`backupId` alone is not a sufficient identity: the same id can exist under a different
endpoint/bucket/server directory, which is precisely the confusion §11.3's sharp edge produces.
Recording the source system identifier is what makes "this evidence is about *that* database"
checkable rather than assumed. `checkProfileDigest` and `manifestDigest` are required because a
version number alone does **not** express whether a check set is stronger, weaker, or merely
different: a weakened profile must **invalidate** older evidence rather than silently inherit its
credibility.

`recoveryTarget.reached` is not self-proving and must be **captured before the recovered cluster
begins normal writes**, since those advance the timeline and LSN past the recovery end point. The
platform therefore reads the reached timeline and LSN at promotion time, as part of the
verification, and records them in the artifact; a value sampled later describes the verification
cluster's own history rather than the restore.

**Where to capture it — measured, because the obvious place is wrong (2026-08-17).** "At promotion"
is necessary but not sufficient guidance: with CNPG the promotion happens inside the **short-lived
`<cluster>-N-full-recovery` job pod**, not in the primary that subsequently serves. That pod's
PostgreSQL log is the only place the archive-recovery completion and the reached timeline/LSN
appear, and it is deleted shortly after the job succeeds. Sampling the eventual primary — the
intuitive choice — is both too late and about a different subject, and yields no recovery evidence
at all. So the requirement is:

> The reached timeline and LSN MUST be read from the recovery job pod's PostgreSQL log, captured on
> successful recovery and before that pod is reclaimed. If that log cannot be captured, the
> verification produces **no** `RestoreVerified` artifact — the restore may well have succeeded,
> but its recovery target is then unevidenced, and an unevidenced target is not a claim this
> platform makes.

The second clause was reached the hard way: a real restore reached "database system is ready" while
the evidence guard refused to write an artifact, because it had sampled the primary. That refusal
is the behaviour §5 and §10 require — the alternative is an artifact whose central field was
inferred rather than observed.

**11.3 Recovery isolation invariant — decided, adopted verbatim** as a hard,
implementation-neutral invariant:

> **A recovery-verification environment MUST have read-only access to the backup source
> under test and MUST write any new backup/WAL artifacts to an isolated destination.**
> (Short form: restore verification MUST be unable to mutate the backup source it is verifying.)

Two additions the spike forced:

1. **Fail-closed refusal.** The platform MUST refuse to start a verification when the recovery
   cluster's own backup destination resolves to the same
   `(endpoint, bucket, pathPrefix, serverName)` tuple as the source under test. The refusal
   surfaces as `RecoveryAssured=Unknown/IsolationUnproven` — **never** as `Valid`, and never as a
   silent skip.
2. **Isolation is observed as well as asserted — but the observation is defense in depth, not a
   complete proof.** The drill MUST attempt a write to the source prefix and require its
   **denial**, using the recovery workload's actual runtime identity (its Secret/ServiceAccount),
   **not** substituted test credentials. So the denial cannot pass vacuously, that same identity
   must first:
   1. authenticate against the **exact** endpoint;
   2. read and verify a known object belonging to the selected `backupId` under the **resolved**
      bucket/prefix/server directory;
   3. attempt a uniquely named `PutObject` under **that same** canonical prefix;
   4. and count only an **authenticated permission denial** as success, recording the client's raw
      response text in the artifact so a reviewer can judge it, plus a post-check that the object
      did **not** land. DNS, TLS, timeout, `NoSuchBucket`, `NoSuchKey`, invalid-credential and
      generic client failures are **inconclusive**, not "denied".

   **Do not assert on the wire-level error code unless the client actually surfaces it.** Measured
   2026-08-17 on ok-robotics: `mc` renders a 403 as `Insufficient permissions to access this path`
   and never emits the string `AccessDenied`, in plain or `--json` output. A probe grepping for
   `AccessDenied` under `mc` therefore cannot pass — the safe direction to fail, but it fails
   *every* run while reporting nothing about isolation, and five consecutive drill runs were lost
   to exactly that. Either use a client that exposes the S3 code (boto3/aws-cli report
   `An error occurred (AccessDenied)`, which is how barman's own errors surface), or match the
   client's documented denial rendering. What must not vary is the surrounding logic: a preceding
   successful authenticated read of a known object under the **resolved** prefix, a non-zero write
   result, the inconclusive set excluded, and the did-not-land check.

   What that proves is exactly one `PutObject` against one key. "Read-only" also excludes
   `DeleteObject`, multipart completion, tagging, copies, and lifecycle or bucket-level
   operations; those cannot be exhaustively black-box tested without risk, because a *successful*
   test would mutate the source. The probe therefore stands **alongside** an inspection of the
   effective policy (or a provider-side authorization evaluation), not in place of it.

**What prefix isolation does NOT cover — measured, not assumed (2026-08-17, ok-robotics).** The
invariant above is about *mutation*, and it holds. Confidentiality of object **names** does not, and
the reason is S3 semantics rather than a policy we chose:

```text
barman-cloud requires HeadBucket
  → S3 exposes no separate HeadBucket action (it is authorized as bucket-level ListBucket)
  → and it accepts no s3:prefix condition
  → so ANY backup-capable identity holds UNCONDITIONED bucket-level ListBucket
  → therefore it can enumerate object names across the whole bucket, including other prefixes
```

Verified by attempting the prefix-conditioned form first: it denied, with the condition key absent
from the request. Object **reads and writes** remain prefix-confined; object **names** are not. So
the honest statement of the boundary is:

> Within one bucket, a prefix confines *access to data*. It does not confine *knowledge of what
> data exists*. Where name confidentiality between consumers is required, the isolation boundary
> is a **separate bucket**, not a separate prefix.

This is exactly the kind of leak §4.2 and the leitprinzip demand be located rather than denied —
and it moves a v1 assumption: `isolation.class: dedicated` must not be read as implying name
confidentiality inside a shared bucket. Shared multi-tenant clusters are already a v1 non-goal
(§9); shared *buckets* now carry the same caveat for the same kind of reason.

The CNPG-specific mechanics remain a spike assumption, not an architecture rule: the source is
declared under `externalClusters[]` with read-only object-store credentials, and the recovery
cluster's own store points at a separate destination. Per head-note finding 3, the isolation check
MUST compare **resolved effective values** — on the plugin path the server directory comes from
the plugin's `serverName` and is overrideable, so comparing `source` names would compare the wrong
thing. (Detail: §5.4)

**11.4 Credential lifecycle semantics — decided.** v1 promises **no** zero-downtime password
rotation, and there is now a mechanical reason rather than a preference: PostgreSQL stores one
verifier per role, so two simultaneously valid passwords for one role do not exist, and CNPG's
`managed.roles[]` binds one `passwordSecret` to one role. What is guaranteed:

- Rotation is **published**: the platform generates the new credential and republishes it in the
  same Secret the consumer already reads.
- Rotation is **asynchronous, not atomic.** Publishing the Secret and applying
  `ALTER ROLE … PASSWORD` are separate reconciliations with no shared transaction: CNPG notices
  the Secret's `resourceVersion` and applies the password afterwards. A consumer can therefore
  read the new Secret *before* PostgreSQL accepts it, and replicas may briefly lag the primary's
  catalogue change. Any contract that says "atomic" here is wrong.
- **"Afterwards" is only prompt if we make it prompt.** CNPG applies an updated credential
  Secret immediately when it carries `cnpg.io/reload: "true"`; without that label the change waits
  for a later reconciliation. The platform MUST therefore set it on credential Secrets it manages —
  otherwise the rotation delay is unbounded and the contract below is unfalsifiable.
- The platform MUST expose an **applied** marker alongside the published credential — a
  reconciliation timestamp or observed generation — so a consumer or operator can distinguish
  "the Secret has been published" from "the database accepts it". Without that marker the
  asynchrony above is real but invisible, which is worse than either a synchronous guarantee or
  an honest one.
- Established sessions are **not deliberately terminated**. The old password stops starting new
  sessions once the change reaches a given server.
- There is no overlap and no grace window for passwords in v1. The consumer therefore carries a
  stated obligation: **reload credentials and retry authentication** during rotation, rather than
  reading them once at boot. §6.2 names this failure mode; v1 resolves it by putting the
  obligation in the contract instead of pretending the platform hides it.
- No timer-based expiry for application roles. Note the mechanism honestly: omitting `validUntil`
  means no expiry, but CNPG may actively set an existing role to `VALID UNTIL 'infinity'` rather
  than leaving it untouched. The contract is "no timer-based expiry", not "the field is never
  written".
- `enableSuperuserAccess: false` by default; superuser is not part of the consumer contract.

Two paths to genuine overlap exist. The absence of overlap is a bound on acceptance, carried as
required work in §13:

1. A **login-role pair** sharing a non-login privilege role — the standard password-overlap
   design, and the only one that works with `managed.roles[]` as used above.
2. **Client certificates.** These give overlap for a *single* role, because PostgreSQL accepts any
   currently valid certificate signed by the trusted CA whose identity maps to that role, and CNPG
   does not manage CRLs, so an old certificate stays usable until it expires. Two conditions must
   be named rather than glossed: certificate generation in CNPG 1.30 belongs to the standalone
   **`DatabaseRole`** resource, so this path means **adopting `DatabaseRole`** instead of the
   inline `managed.roles[]` used here, and it additionally requires a matching `pg_hba` rule for
   certificate authentication.

So "overlap requires a role pair" is true of **passwords**, not of credential rotation in general
— and the certificate route is a change of resource model, not a flag.

(Detail: §6.2)

## 12. Composition mechanism — resolved

The `???` is **Crossplane**, resolved by this section's own consistency clause rather than by
preference. Crossplane v2.3.3 already serves seven XRDs on ok-mgmt — cluster provisioning,
upgrade and cleanup, OpenRMF, OpenWebUI, Vault instance and Vault config — all under
`platform.openkubes.ai`. A thin bespoke controller would be a second mechanism for a job the
first one already does, and the ADR's own criterion says consistency wins in exactly that case.

```text
OpenKubes Database Contract → Crossplane XRD + Composition → CloudNativePG
```

The API surface is `Database` / `DatabaseClaim` in group `platform.openkubes.ai` (note: **not**
the `platform.openkubes.org` of §6's sketch, which no served XRD in this platform uses). The kind
stays contract-shaped rather than engine-shaped because §4 and §8 make the contract the product;
what keeps that honest is `engine.name` being a closed enum containing only `postgresql`, so
adding an engine later is an enum widening rather than a rename of a served kind.

**Offering a `DatabaseClaim` is a deliberate choice of Crossplane's legacy model, not an
oversight.** Under Crossplane v2 the claim/XR split is the legacy `apiextensions.crossplane.io/v1`
shape; v2-native XRDs drop claims in favour of namespaced XRs. This capability takes the legacy
shape because every capability already served on ok-mgmt uses it, and because the authority
boundary this platform relies on (§11.3-style fail-closed admission over an explicit
`(group, claimNamespace, claimName, clusterRef, …)` tuple list) is written against claims today.
Migrating to namespaced XRs is a platform-wide move, not something one capability should do
unilaterally — and doing it here first would mean this capability's authority policy is the only
one shaped differently from the rest.

**That choice now carries a deadline, confirmed by the API server (2026-08-18).** Installing the XRD
on ok-mgmt emitted: *"CompositeResourceDefinition v1 is deprecated and will be removed in a future
release; consider migrating to v2."* So the legacy claim model is not merely older — it is on a
removal path, and every capability in this platform is on it together. This does not change the v1
decision (consistency with the seven XRDs already served, and an authority policy written against
claims), but it converts "migrate eventually" into scheduled work with an external clock, and the
migration is platform-wide rather than per-capability. It belongs on the platform backlog, not in
this ADR's open bounds.

Composition is via **provider-kubernetes `Object`**, not provider-helm: the composed resources are
CNPG custom resources rather than a chart, and `Object.status.atProvider.manifest` gives the
Composition read-back of observed CNPG state, which is what the Evidence Contract has to consume.
Three consequences must be stated rather than discovered later:

- **Read-back is raw.** `status.atProvider.manifest` does not become `Database.status` or
  `RecoveryAssured` by itself. A composition function must explicitly consume the observed
  resource, project selected fields into the XR status schema, and handle observation age and
  observation failure. Timeliness depends on the installed provider version's watch/poll
  behaviour, so freshness of the *observation* is itself part of the evidence, not a given.

  **Measured on ok-mgmt, 2026-08-18 — the two stages lag independently.** The composite reconciler
  is *not* frozen: Crossplane's own counter for `composite/databases.platform.openkubes.ai` advanced
  by 3 `requeue_after` reconciles in 150 s (≈1 per 50 s, the default poll). Sampling the XR for 8
  minutes showed no status change, which is the *correct* result and proves nothing on its own —
  recomputation from unchanged source timestamps is idempotent, and Kubernetes does not bump
  `resourceVersion` on a no-op write. The unconfounded observation is on the provider stage: the
  composed `ObjectStore` `Object` carried `status.atProvider.manifest.status: {}` while ok-robotics
  had held a populated `serverRecoveryWindow` since 10:54:47Z, and it populated within 15 s of a
  no-op annotation on that `Object`. Whether it would have self-corrected on the provider's own next
  sync was not established, so the propagation delay is **observed to be non-zero and not yet
  bounded**. Bounding it is delivery work, not a documented property.
- **An `Object` observes one named resource, and scheduled backups have generated names.** A
  static `Object` cannot enumerate `Backup` CRs. Collecting them requires either a listing
  facility proven present in the pinned provider version, or a small evidence function/controller
  that lists labelled `Backup` objects in the workload cluster. This is a real gap in the
  mechanism, not a detail of wiring.
- **Deletion semantics differ by resource, and the default is wrong for the important one.** The
  production CNPG `Cluster` MUST use `deletionPolicy: Orphan`: deleting the composed `Object` can
  delete the remote `Cluster`, and Kubernetes ownership can cascade from there into PVC deletion.
  Destruction belongs to a separately authorized decommission workflow. Disposable verification
  clusters are the opposite case and use `Delete`. Remote-cluster unreachability cuts both ways and
  must be handled: `Delete` can strand the XR behind finalizers, while `Orphan` can complete
  without proving anything was removed — an `Orphan` deletion therefore reports what it left
  behind rather than claiming removal.

  **The collision contract `Orphan` implies, decided here rather than left open:** when a
  `Database` is provisioned and a matching CNPG `Cluster` already exists on the target from an
  earlier orphaned lifecycle, the platform MUST **refuse and surface the collision**
  (`OperationalReady=False/OrphanedResourceCollision`, naming the existing object) instead of
  adopting it. Silent adoption is the dangerous direction: it would attach a new contract, new
  credentials and a new backup destination to somebody else's live data, and the failure would
  surface as data loss rather than as a rejected claim. Adoption remains possible but only as an
  explicit, separately authorized step that records what is being adopted — the same shape as the
  decommission workflow, and for the same reason.

**Backup mechanism.** The CNPG-I plugin path (`spec.plugins` plus an `ObjectStore` resource) is
chosen over the in-tree `spec.backup.barmanObjectStore`, which is deprecated in 1.30. Two honesty
constraints follow, and the second bounds what this ADR may currently assert:

- The Barman Cloud Plugin version MUST be pinned explicitly. `ObjectStore` status, retention,
  metrics and parameters are **plugin** behaviour and are not guaranteed by saying "CNPG 1.30".
- **The plugin version is now selected and its status surface observed** (updated 2026-08-18).
  `barman-cloud.cloudnative-pg.io` **v0.14.0** is pinned, and §11.1's current-availability source
  has been read from a live cluster rather than inferred from a schema: `ObjectStore.status`
  carried exactly one key, `serverRecoveryWindow`, holding `firstRecoverabilityPoint` and
  `lastSuccessfulBackupTime` per server name. §11.1 may therefore assert those field names for
  this pinned version — and only for it. The general constraint above stands: the names are plugin
  behaviour, so a version bump re-opens this and must re-observe the surface, not assume it.

**Still deliberately open — and one thing that only looks like it.** Whether the capability is
ultimately called `ok-dbaas` is genuinely unsettled and costs nothing to leave open. §6.1 residency
(`dataPolicyRef`) is different: it is **not implemented in v1** because this platform has no
policy-resolution mechanism, and a claimant-writable reference to a non-existent policy object would
be worse than its absence, so `protection.policyRef` is a closed enum (`development` | `production`)
for now. §13 carries it as bound 7.

## 13. Path to Acceptance — Architektur-Spike

This ADR is **`Accepted`** (see the header). The path below is the route it took; the diagram
records the sequence, not the current position:

```text
Proposed ADR
│  ├── hält die Architekturgrenze fest
│  ├── dokumentiert die konvergierten Prinzipien
│  ├── benennt offene Entscheidungsfragen (§11, §12)
│  └── definiert, welche Evidence für Accepted nötig ist
│      (§11, §12 decided 2026-08-17 — this diagram shows the path, not the current position)
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

**Acceptance criterion (four parts, not three).** This ADR becomes `Accepted` when the spike
delivers a decided semantics for each of §11.1–§11.4, resolves the `???` composition question
(§12) with its rationale, checks the CNPG assumptions (see the note on sources) against the target
version — **and** produces the evidence the spike path above calls `Evidence + Decision`: an
executed restore-drill verification. That fourth part was always in the diagram but missing from
this list; closing the gap here prevents two readings of the criterion standing side by side.

**Where that criterion stands (2026-08-17). All four parts are met *as an architecture spike*,
and the fourth deserves care.** The drill ran and its result is real; the artifact it produced is
**not admissible evidence** under the typed `RestoreVerified` contract that this same work
introduced (it lacks the identity binding §11.2 now requires, and its `checks[]` results were
written as constants rather than derived). Treat what follows as the historical record of an
executed verification, not as the v1 evidence the Evidence Contract will accept. That re-run is
named in the open items below. §11.1–§11.4 are decided
(§11); §12 is resolved with its rationale and its stated costs; the head-note assumptions have been
checked in two distinct ways that must not be conflated: against the installed CRD **schema
surfaces** of 1.30.0 (which establishes API shape only, as the note on sources says), and — for the
claims the drill exercised — against **observed runtime behaviour**, which corrected the three
head-note findings plus the major-upgrade shortcut. The restore drill has been **executed** on
ok-robotics, producing

```text
evidence: platform/database/postgresql/drill/evidence/restoreverified-20260817t114640z.yaml
  backupId 20260817T104456 · sourceSystemIdentifier 7674943119728799765
  recoveryTarget.reached  timelineId 2, lsn 0/80001D0   (from the promotion log)
  duration PT75S · checkProfileDigest + manifestDigest recorded
  NOT ADMISSIBLE under §11.2's typed contract: no databaseRef identity binding, and checks[]
  results written as constants. Superseded by the JSONL-derived writer; a re-run is required.
  isolation: authenticated read OK, write refused ("Insufficient permissions"), object absent
  cnpg 1.30.0 · plugin barman-cloud.cloudnative-pg.io 0.14.0
```

What the drill actually established, as installed on ok-robotics:

```text
cert-manager                        installed, proven by issuing a certificate
Barman Cloud Plugin  v0.14.0        PINNED — closes the §12 open item
                                    NOTE: its manifest does not create cnpg-system; that namespace
                                    must pre-exist or every namespaced object fails NotFound
CNPG 1.30.0                         operator Ready
MinIO, TLS via cert-manager         three identities: source writer, source reader, drill writer
provider-kubernetes ProviderConfig  INSTALLED on ok-mgmt 2026-08-18 (attended, gated)
```

The drill deliberately does not need that last prerequisite: it exercises CNPG directly, so the
evidence above stands independently of the Crossplane path.

**The Crossplane path has since been installed and exercised end to end (2026-08-18).** Installing
the XRD, Composition and ProviderConfig on ok-mgmt was a separate attended step, because it mutates
a management plane and no document change may carry that with it; it required a second explicit
acknowledgement (`ACCEPT_PROTOTYPE_LIMITS=yes`) so that a successful install could not be read as
closing the bounds below. A claim was then admitted, composed all seven resources onto ok-robotics,
and the resulting `Database` XR computed its evidence **from live observed state**:

```text
Database ok-robotics-7x6l2 · uid a6b4b2ff-38f3-4cdf-ab2e-c7808d5e6326
  operational  Valid    ClusterReady
  protection   Valid    BackupCompletedAvailableAndArchivingNotFailing
                        execution Valid/BackupCompleted · availability Valid/
                        BackupWindowContainsExecution · archiving Valid/ContinuousArchivingNotFailing
  recovery     Unknown  VerificationPending          (bound 2 — no admitted artifact yet)
  capability   Failed   RequestedCapabilityAbsent    (bound 4 — pgvector absent)
  serviceReady False    — correct: the policy is a set, and two dimensions are not Valid
```

This is the first evidence in this ADR produced by the composition mechanism itself rather than by
the drill runner, and it is what makes §5.1's "set, not pipeline" claim observable: `protection`
reached `Valid` while `capability` was `Failed`, with no ordering between them.

**Verifying recovery against a composed `Database` exposed a gap the earlier drill could not see.**
The 2026-08-17 run used the drill's own `source-cluster.yaml`, which seeds a known row; a Database
provisioned by this Composition gets an **empty** `app` database from initdb, so the semantic profile
had nothing to read and the runner **correctly aborted rather than record a check it could not run**
(`restore_probe` absent → non-zero psql, no evidence written). Verification therefore requires known
content, and nothing in the contract puts any there. For this run the row was seeded by hand and a
fresh backup taken. That is acceptable for a spike and **not** acceptable as a delivery design: an
automated recovery verification either seeds and owns its own probe object inside the protected
database, or it must verify something whose presence the platform can guarantee without writing to
the claimant's data. Choosing between those two is delivery work under bound 3, and it is a contract
question — writing into a claimant's database is not obviously the platform's right.

```text
drill 20260818t115710z · backupId 20260818T115641 · timeline 2 · lsn 0/6000120 · PT74S
  checks   outside-recovery · known-row-readable · restore-probe-heap-readable ·
           primary-key-index-readable · selected-backup-object-readable — all PASS, all derived
  isolation effective source policy verified against MinIO (not the authored file);
           authenticated write refused ("Insufficient permissions"); written object absent
  admitted server-side dry run against the ok-mgmt CRD; databaseRef binds name AND uid
```

**What is still NOT evidenced, and therefore bounds this acceptance.** Seven items, listed because a
bounded acceptance is only honest if the bounds are enumerated. The last three were found by
installing the capability and operating it — the kind of gap only a live pipeline reveals. None of them invalidates the
contracts; each blocks *delivered-capability* acceptance.

```text
1. RPO freshness is unobservable        → ProtectionReady=Valid unreachable, so `production` is
   (§11.1's third signal)                 unreachable. Renders Unknown/RPOFreshnessUnproven by
                                          design rather than via a proxy. Needs a WAL age/backlog
                                          observation the Composition can actually see.
2. RecoveryAssured needs an operator    → the re-run is DONE (2026-08-18): the drill produced
   act, not more machinery                  restoreverified-20260818t115710z.yaml against the
   (re-run completed 2026-08-18)            composed Database, carrying the databaseRef identity
                                          binding (uid a6b4b2ff-…) with all five checks derived
                                          from observed values, and the ok-mgmt API server admits
                                          it (server-side dry run). What remains is not code: per
                                          §7 the operator group's CREATION of that CR *is* the
                                          approval, so `RecoveryAssured=Valid` waits on a human
                                          act by design. Continuous re-verification is bound 3.
3. Scheduled-backup enumeration        → §12: a static provider-kubernetes `Object` cannot
   is missing                             enumerate generated-name Backup CRs, so the fixed
                                          evidence anchor eventually leaves the moving recovery
                                          window even while backups are healthy. Continuous
                                          delivery is therefore unproven; a collector is v2.
4. Capability delivery                 → no functional probe feeds CapabilityConformant, and
   (was the only item named before)       extension delivery additionally needs the Kubernetes
                                          ImageVolume feature gate (disabled on the drill cluster).
5. Observation freshness is absent      → every `observedAt` this Composition writes is a SOURCE
   from the status surface                 event timestamp (`lastTransitionTime`, `stoppedAt`,
   (added 2026-08-18, from the            `lastSuccessfulBackupTime`) and never an observation
    live install)                         time, so nothing in `status` says when the platform last
                                          successfully looked. `Stale` closes a different gap: it
                                          fires when the SUBJECT ages out of its validity window,
                                          not when the OBSERVER stops. The asymmetry that follows
                                          is worth stating plainly — a frozen read-back under a
                                          live reconciler does eventually degrade, because the
                                          ageing check keeps re-evaluating against current time,
                                          whereas a frozen reconciler cannot degrade at all: its
                                          last verdict persists verbatim and, every timestamp in
                                          it being a real source event, reads as a recent and
                                          definite Valid. Needs an explicit observation-freshness
                                          field and a measured propagation bound (§12).
6. Credential rotation has no overlap    → §11.4: publishing the Secret and applying ALTER ROLE are
   (§11.4, and OK-145's fourth AC          two separate reconciliations, so there is a window in
    asked for this to be decided)          which the published credential is not yet the accepted
                                          one, and v1 makes the consumer carry reconnection.
                                          OK-145's fourth AC asked for the overlap and grace
                                          period to be decided; "none" is an answer that leaves
                                          the requirement owed. Needs a login-role pair sharing a
                                          non-login privilege role, or client certificates.
7. Residency is a contract field with    → §6.1: `dataPolicyRef` describes residency as policy plus
   no resolution mechanism                 evidence, but this platform has no policy-resolution
   (§6.1)                                  mechanism, so the field is absent in v1 rather than
                                          claimant-writable and dangling. `protection.policyRef`
                                          is correspondingly a closed enum. Needs a policy object
                                          and a resolver before residency can be asserted at all.
```

The two causes behind item 4, neither of which sits in this contract:

```text
1. no functional capability probe exists      → CapabilityConformant=Valid is unreachable for a
   (the v1 gap that actually blocks it)          requested capability. Two distinct outcomes, and
                                                 the observed one is the stronger: extension
                                                 PRESENT but unprobed → Pending/
                                                 CapabilityProbePending; extension ABSENT →
                                                 Failed/RequestedCapabilityAbsent, which is what
                                                 ok-robotics reports, the gate being off
2. image volumes non-functional on the       → CNPG's declarative extensions are image volumes
   target platform (k8s/runtime, not CNPG)      (KEP-4639). With the gate off none can mount;
                                                with the gate ON the container cannot be created
                                                (`failed to mkdir ""`). Reproduced with the gate
                                                both beta-enabled and GA, across two Talos and
                                                two containerd versions. NOT root-caused. A
                                                bundled image delivers pgvector 0.8.6 without
                                                image volumes, at the cost of a fixed extension
                                                set (weaker than §6.4).
```

So a `Database` requesting `postgresql.extension.pgvector` is out of v1 scope. Closing it needs a
probe that exercises the capability (§6.3's rule, applied at provisioning) and a platform on which
image volumes actually mount — the latter belongs in the capability's cluster requirements, alongside
cert-manager and the pinned plugin. The probe half is delivered under OK-150: `CapabilityVerified`
(§11.2's evidence pattern applied to capability) plus a Composition that reaches
`CapabilityConformant=Valid` only from an admitted artifact bound to the running image digest.

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
