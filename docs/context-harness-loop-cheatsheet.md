# Context, Harness & Loop Engineering — Azubi-Spickzettel

> Eine Seite. Erst Kontext, dann Leitplanken, dann Automatisierung.
> Am OpenKubes-Beispiel erklärt.

---

## Die drei Begriffe in einem Satz

| Begriff | Frage | Werkstatt-Bild |
|---|---|---|
| **Context Engineering** | Welche Infos braucht die KI *jetzt*? | Der Arbeitsauftrag |
| **Harness Engineering** | Welche Werkzeuge, Regeln, Kontrollen braucht sie? | Die Werkstatt |
| **Loop Engineering** | Wie wiederholt sie den Ablauf selbstständig? | Das Fließband |

**Merksatz:** *Context* sagt, was wichtig ist. *Harness* sorgt dafür, dass es richtig gemacht wird. *Loop* sorgt dafür, dass es wiederholt gemacht wird.

---

## 1. Context — die richtigen Infos, nicht alle Infos

Die KI bekommt genau das, was sie für den nächsten Schritt braucht: Aufgabe, Regeln, relevante Dateien, Beispiele, Ziele, Einschränkungen.

**Schreibtisch-Regel:** Mehr Infos ≠ besser. Je mehr Unnötiges herumliegt, desto leichter übersieht die KI das Wichtige. Alte Doku, fremde Projektdateien, ungefilterte Logs → raus.

**Just-in-time:** Nicht alles auf einmal laden. Erst Übersicht, dann nur die betroffenen Dateien nachladen.

**Bei OpenKubes:** Für „Observability in `ok-cluster` integrieren" braucht der Agent das Jira-Ticket, ADR-Platform-018, die Schnittstellen von `ok-observability` und die Acceptance Criteria — **nicht** alle Repos komplett.

---

## 2. Harness — Werkzeuge & Leitplanken

**Guides (vor der Arbeit):** ADRs, `README.md`/Repo-Regeln, API-Spec, Namenskonventionen, Beispiel-Module, Definition of Done.

**Sensors (nach der Arbeit):** `make validate`, Schema-/Manifest-Validierung, Linter, Architekturtests, Security-/Policy-Checks, Readiness-Gates, PR-Review.

**Formel:** `Modell + Werkzeuge + Regeln + Kontrollen`

**Bei OpenKubes:** Der Agent darf nicht nur YAML erzeugen — er muss `make validate`, Architekturtests und das Observability-Readiness-Gate grün durchlaufen.

---

## 3. Loop — den Ablauf wiederholen

```
Solange offene Aufgaben:
  1. Ticket / nächste Aufgabe lesen
  2. Relevante ADRs + Dateien laden
  3. Änderung umsetzen
  4. Tests + Gates ausführen
  5. Fehler korrigieren
  6. Fortschritt dokumentieren (Jira / PROGRESS.md / Git)
  7. Nächsten Schritt wählen
```

**Abbruchbedingung:** alle Acceptance Criteria erfüllt — oder eine Architekturentscheidung braucht einen Menschen.

**Memory:** Fortschritt außerhalb der KI sichern (Jira-Ticket, `PROGRESS.md`, Git-Commits), damit der Agent nach Neustart weiterarbeiten kann.

**⚠️ Gefahr:** Ein Loop wiederholt auch Fehler. Ohne Loop → 1 falsche Klasse. Mit Loop → 50 falsche Klassen. Darum braucht **jeder** Loop starke Kontrollen und eine klare Abbruchbedingung.

---

## Diagnose — was fehlt gerade?

- **Agent versteht die Aufgabe falsch** → Kontext prüfen (Ziel eindeutig? richtige Dateien? Architektur bekannt? aktuell? Beispiel da?)
- **Agent verletzt Projektregeln** → Harness verbessern (Regeln dokumentiert? Tests? Architekturprüfung? erkennt er eigene Fehler?)
- **Agent gut, aber ständig neu anstoßen** → Loop bauen (nächste Aufgabe automatisch? Fortschritt gespeichert? Kontrollen? sichere Abbruchbedingung?)

---

## OpenKubes-Merksatz

> **ADRs und Tickets** erklären, was richtig ist.
> **Tests und Gates** prüfen, ob es richtig umgesetzt wurde.
> **Der Loop** arbeitet weiter, bis die nachweisbaren Kriterien erfüllt sind.

---

## Sonderfall: Unser 3-Wege-Review *ist* ein Loop

Ihr habt mit **Arash / Claude / GPT** bereits einen **menschlich gesteuerten Architektur-Review-Loop**:

```
ADR-Entwurf → Reviewer A (Claude) → Reviewer B (GPT) prüft ADR + Review A
   → Konflikte & Konsens extrahieren → Autor überarbeitet
   → Fakten-/Conformance-Check → Approve / Changes / Human Decision
```

**Sensor-Diversität (der Kern):**

- **Claude** → innere Logik, Gegenargumente, Widersprüche
- **GPT** → Governance-Sprache, Begriffspräzision, Cross-ADR-Konsistenz
- **Git / Jira / okgraph** → überprüfbare Fakten

Zwei *identische* Reviewer würden nur dieselben blinden Flecken duplizieren.

**Das Merge-Gate ist der wichtigste Harness-Teil:** *AI may argue; only humans merge.* Es ist gleichzeitig Sicherheitsgrenze, Abbruchbedingung, Verantwortungszuordnung und Schutz vor automatisierter Fehlervervielfachung. Weil der Mensch merged, kann der Loop keine 50 falschen ADRs produzieren.

**Automate the facts / Keep the decision human:**

| Gut automatisierbar (Fakten) | Bewusst menschlich (Urteil) |
|---|---|
| Existiert der referenzierte ADR? | Welches Gegenargument ist *wirklich* relevant? |
| Stimmt ADR-Titel & Status? | Ist ein Konflikt sprachlich oder architektonisch? |
| Existiert das Jira-Ticket? | Ist der Kompromiss tragfähig? |
| Stimmen Commit-Hash & Repo? | Echter Konsens oder oberflächliche Zustimmung? |
| Links/Abhängigkeiten konsistent? | Soll die Entscheidung überhaupt getroffen werden? |
| okgraph: widersprüchliche Kanten? | |

**Warum das manuelle Übertragen zwischen Reviewern ein *Feature* ist:** Der Medienbruch sieht wie ein Automatisierungsdefizit aus, hält aber den menschlichen Entscheider kognitiv im Loop. Eine Auto-Zusammenfassung wäre effizienter — würde aber genau den Verständnisverlust fördern, vor dem Loop Engineering warnt.

**Eigener blinder Fleck:** Wenn Claude und GPT sich *zu schnell* einig sind, ist das selbst ein Sensorsignal — kein Grün, sondern ein Hinweis, genauer hinzusehen. Ein Loop, in dem beide Reviewer immer zustimmen, ist funktional ein Loop mit nur einem Reviewer. Der Wert entsteht dort, wo sie sich *widersprechen*.

---

> **The process that creates the architecture is part of the architecture.**
>
> Automate the facts. Augment the reasoning. Keep the decision human.
