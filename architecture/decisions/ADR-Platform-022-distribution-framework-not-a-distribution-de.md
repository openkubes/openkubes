# ADR-Platform-022: OpenKubes ist ein Distributions-Framework, keine Distribution

**Datum:** 2026-07-17
**Status:** Draft — Akzeptanzbedingung ausstehend (siehe unten)
**Erweitert:** ADR-Platform-001
**Präzisiert:** ADR-Platform-002

---

## Kontext

Am 16.07.2026 hat das Projekt seine öffentliche Aussage neu positioniert:

> **„OpenKubes ist ein Framework zum Bau souveräner Kubernetes-Plattform-Distributionen."**

Das README, das Architekturdiagramm, die GitHub-Beschreibung und das Launch-Meetup wurden entsprechend aktualisiert — bevor ein Decision Record existierte. Nach der eigenen Doktrin des Projekts („keine Implementierung ohne committeten Decision Record") ist dieses ADR nicht optional: Es untermauert die Aussage — oder erzwingt ihre Rücknahme.

Die Aussage erzeugt einen scheinbaren Konflikt mit ADR-Platform-002, das festlegt, dass `openkubes/openkubes` die Platform Distribution and Integration Layer *ist*. Ein Framework ist per Definition keine Distribution. Das Yocto-Projekt löst dieselbe Spannung explizit: Yocto ist das Framework; **Poky** ist die Referenzdistribution, die mitgeliefert wird, damit das Framework nicht abstrakt bleibt. OpenKubes hat beide Rollen stillschweigend in einem Repository getragen, ohne sie zu benennen.

Eine zweite Beobachtung aus derselben Neupositionierung: Das Framework — sofern es existiert — wurde nicht vorab entworfen. Es wurde nachträglich aus einer funktionierenden Distribution extrahiert — die Contracts, die ADR-Methode und die Contract Tests wurden in `ok-linux`, `ok-cluster` und `capi-platform-v4.2` (ADR-001) entdeckt, nicht vor ihnen erfunden.

## Entscheidung

> OpenKubes ist ein **Distributions-Framework**: die Capability Contracts, die Entscheidungsmethode (ADRs mit Three-Way-Review) und die Contract Tests. Alles andere — die XRD/Composition-Verdrahtung, die `ok-*`-v1-Implementierungen, die End-to-End-Beispiele, die operativen Assemblies — bildet die **Referenzdistribution**, die mit diesem Framework gebaut wurde.
>
> `openkubes/openkubes` beherbergt beides — so wie das Yocto-Projekt sowohl OpenEmbedded-Core als auch Poky beherbergt. ADR-Platform-002 wird hiermit neu gelesen, nicht abgelöst: „Platform Distribution and Integration Layer" beschreibt die *Referenzdistributions*-Rolle dieses Repositories; die Framework-Rolle (Contracts, ADRs, Contract Tests) steht darüber.

### Was das Framework materiell ist

Das Wort „Framework" weckt Code-Erwartungen (ein SDK, Generatoren, eine Runtime). Das OpenKubes-Framework ist nichts davon. Es besteht aus genau drei Artefaktklassen:

1. **Capability Contracts** — die API des Frameworks gegenüber Distributionsbauern
2. **Die Entscheidungsmethode** — ADRs, Forcing-Consumer-Disziplin, Three-Way-Review
3. **Contract Tests** — das Verifikationsinstrument des Frameworks (und perspektivisch seine Konformitäts-Suite — siehe Konsequenzen)

### Die Kette, aus Framework-Perspektive neu gelesen

| Kettenelement | Plattform-Lesart (bisher) | Framework-Lesart (dieses ADR) |
|---|---|---|
| Capability | Was die Plattform kann | Das Vokabular des Frameworks — was eine Distribution enthalten *darf* |
| Contract | Schnittstelle zwischen Plattformschichten | Die API des Frameworks gegenüber Distributionsbauern |
| Implementation Profile | Werkzeugwahl (Talos, Longhorn, …) | Der Akt des Distributionsbaus — Profile zu verfassen oder auszuwählen *ist* Distributionsarbeit |
| Provider Values | Standortspezifische Konfiguration | Eine Distributions-*Instanz* — niemals ein Framework-Artefakt (die gerenderten Instanz-Verzeichnisse in `ok-cluster` sind bewusst veröffentlicht: Sie enthalten nur unkritische private IPs; Geheimmaterial entsteht zur Laufzeit und gelangt nie in Git; die Cluster-Instanzen selbst sind nur per VPN erreichbar) |
| Contract Tests | Provisionierungs-Gate (ADR-018) | Die Konformitäts-Suite des Frameworks im Keim |

### Grenzklärung (Neulesung, kein Widerspruch)

Das README besagt „jedes Repository besitzt genau einen Capability Contract". Dieses ADR schärft diese Formulierung: Capability Contracts **leben** in `openkubes/openkubes` (dem Framework); die `ok-*`-Repositories sind **v1-Referenzimplementierungen** dieser Contracts und gehören zur Referenzdistribution. Sie sind austauschbar — eine Distribution, die `ok-storage` gegen ihre eigene Storage-Implementierung tauscht und dabei die Storage Contract Tests besteht, ist weiterhin eine OpenKubes-Distribution. Das ist der präzise Sinn, in dem „OpenKubes owns the contracts, not the components" (ADR-001) auf die Framework-Ebene ausgedehnt wird.

## Akzeptanzbedingung

Dem ADR-020-Muster folgend bleibt dieses ADR **Draft**, bis ein Forcing Consumer für die Framework-Aussage selbst existiert:

> **Eine erste externe Distribution** — ein Assembly, das nicht vom Kernteam gebaut wurde, mit eigener Implementation-Profile-Auswahl und eigenen Provider Values, betrieben gegen die OpenKubes Capability Contracts.

Was die Bedingung *nicht* erfüllt:

- `ok2-rmf` / Open-RMF (ADR-019): ein zweiter **Consumer** und eine Plattform-**Instanz**. Er validiert die Contracts (und hat ADR-020 zu Accepted gezwungen), aber er assembliert keine eigene Distribution.
- Weitere interne Cluster: Instanzen der Referenzdistribution, keine Distributionen.

Bis die Bedingung erfüllt ist, ist die öffentliche Aussage eine **These mit definiertem Falsifikationskriterium** — und dieses ADR ihr ehrliches Protokoll.

## Begründung

- **Das Framework ist jünger als seine erste Distribution — by design.** Ein Framework, das vor seinen Distributionen erfunden wird, verletzte das Forcing-Consumer-Prinzip („no structure without a forcing consumer"). Ein Framework, das aus einer funktionierenden Distribution extrahiert wurde, ist der Beleg, dass die Abstraktion real ist. „Discover, don't invent" — angewandt auf die Identität des Projekts selbst.
- **Die Yocto-Analogie ist strukturell, nicht rhetorisch.** Yocto ist keine Linux-Distribution; es ist das Framework, aus dem Distributionen hervorgehen, mit Poky als mitgeliefertem Beweis. Sie beantwortet auch die Abgrenzungsfrage gegenüber kubespray und Cluster API: Deren Schicht ist Provisionierung; die OpenKubes-Schicht sind Contracts. Historisch existierte OpenEmbedded, bevor es jemand ein Framework nannte — dieselbe Bootstrap-Reihenfolge wie hier.
- **ADR-001 trägt die These bereits.** „Contracts, not components" *ist* die Framework-Aussage avant la lettre; dieses ADR erweitert sie um eine Ebene nach oben, statt ein neues Prinzip einzuführen.
- **Dieses ADR heilt einen Doktrinbruch.** Die README-Neupositionierung ging live, bevor ein Decision Record existierte. Die Aussage als Draft mit Akzeptanzbedingung zu protokollieren — statt sie per Marketing-Dekret für Accepted zu erklären — ist die einzige Auflösung, die mit den eigenen Regeln des Projekts vereinbar ist.
- **Ehrlicher Status ist eine Stärke.** Die Framework-These auf Basis von null externen Distributionen für Accepted zu erklären, wäre exakt das „structure without a forcing consumer"-Versagen, das die Doktrin verhindern soll.

## Betrachtete Alternativen

| Alternative | Warum verworfen |
|---|---|
| ADR-002 ändern statt neues ADR | Versteckt die Identitätsentscheidung des Projekts in einer Fußnote zu einer Repository-Scoping-Entscheidung; der Knowledge Graph hätte keinen expliziten Knoten für die Framework-These |
| Das ADR jetzt für Accepted erklären, unter Verweis auf ok2-rmf | ok2-rmf ist Instanz/Consumer, keine Distribution; eine Annahme auf dieser Beweislage verletzte das Forcing-Consumer-Prinzip, das dieses ADR selbst anführt |
| Die Framework-Aussage zurückziehen, bis eine Distribution existiert | Verliert die Zugkraft der These; die Aussage mit veröffentlichtem Falsifikationskriterium lädt den Consumer, der sie beweisen würde, aktiv ein |
| Die Referenzdistribution jetzt benennen (ein „Poky" für OpenKubes) | Structure without a forcing consumer: Solange nur eine Distribution existiert, hat ein unterscheidender Name nichts zu unterscheiden. Der Name wird fällig an dem Tag, an dem eine zweite Distribution erscheint |
| ADR-002 supersedieren | Die Entscheidung von ADR-002 bleibt für die Referenzdistributions-Rolle korrekt; nach dem ADR-003-Präzedenzfall wird Geschichte neu gelesen, nicht deprecated |

## Konsequenzen

**Positiv:**

- Die öffentliche Aussage und der Decision Record sind versöhnt; der Doktrinbruch vom 16.07.2026 ist geschlossen
- Jedes Kettenelement erhält eine zweite, schärfere Lesart (Tabelle oben), ohne dass sich ein Artefakt ändert
- Die Provider-Values-Grenze von `ok-cluster` wird nun durch die Architektur erklärt statt durch Policy: Instanz-Verzeichnisse dürfen public sein, wenn sie kein Geheimmaterial tragen — die Sensitivität liegt in der Erreichbarkeit (VPN-only-Cluster), nicht im Repository
- Ein künftiges Konformitätsprogramm hat einen definierten Keim: Contract Tests zertifizieren die behaupteten Capabilities einer Distribution („Built with OpenKubes" wird verifizierbar). **Trigger:** dieselbe erste externe Distribution; keine Konformitätsarbeit vorher
- Die Namensfrage für die Referenzdistribution ist explizit zurückgestellt, mit definiertem Trigger

**Negativ / Trade-offs:**

- Das Projekt behauptet öffentlich, ein Framework zu sein, während sein eigener Decision Record „These, Beweis ausstehend" sagt — diese Asymmetrie muss ausgehalten und in Vorträgen ehrlich dargestellt werden (sie ist zugleich eine überzeugende Geschichte)
- Der README-Satz „jedes Repository besitzt genau einen Capability Contract" braucht eine nachgelagerte Formulierungsanpassung, um zur Grenzklärung zu passen
- Zwei Rollen in einem Repository (Framework + Referenzdistribution) verlangen anhaltende Disziplin in Reviews: „Ist diese Datei ein Framework-Artefakt oder ein Distributions-Artefakt?"

**Neutral:**

- Aus diesem ADR folgen keine Repository-Verschiebungen, keine Codeänderungen, keine Umbenennungen
- ADR-Platform-002 bleibt Accepted; sein Geltungsbereich wird durch Neulesung verengt, konsistent mit dem ADR-003-Präzedenzfall
