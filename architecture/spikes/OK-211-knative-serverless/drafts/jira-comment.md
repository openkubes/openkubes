<!-- Entwurf für einen Kommentar in OK-211 (Deutsch, wie für Jira vereinbart). Nicht gepostet. -->

**Spike-Ergebnis OK-211 — Knative als optionales Serverless-/Event-Capability**

Vorgeschlagenes Ergebnis: **CONDITIONAL GO**. Wir schlagen vor, einen ADR für ein **opt-in** Capability zu entwerfen, mit zwei produktneutralen Contracts: request-getriebene Workloads und Event-Routing. Knative wäre das erste Implementation Profile, zunächst im Envelope `datacenter`. Das ist kein Rollout und keine Implementierungszusage. Entscheidung im Three-Way-Review (Gawenda, Arash).

Getestet auf einer eigenen VM im ok-local-Profil: K3s v1.35.5, Knative 1.23 → 1.24.

- **Serving:** Scale-to-Zero ≈ 95 s mit Defaults. Kaltstart mit gecachtem Image Median 1,35 s, ohne Cache 7–9 s (davon 73–79 % Pull). Autoscaling 0 → 6 Pods in 9 s, 0 Fehler bei 1,1 Mio. Requests. Traffic-Split, Tag-Route und Rollback funktionieren.
- **Eventing:** Zustellung, Filter, Retries und Dead-Letter-Sink funktionieren. Der InMemoryChannel ist nicht dauerhaft: Bei einem Dispatcher-Restart gingen alle Events verloren, die gerade in Zustellung waren. Der Sender erhielt dabei immer einen Fehler.
- **Upgrade 1.23 → 1.24 unter Last:** 0 von 476 Requests fehlerhaft. Dafür waren drei Ableitungsregeln an den Release-Manifesten nötig, weil das Server-Side-Apply sonst an Feldern scheitert, die Controller zur Laufzeit besitzen.
- **ADR-010:** Ein einziger Einstiegspunkt über Traefik (`ok-ingress`) mit Kourier als ClusterIP funktioniert. TLS endet bei Knative aber an Kourier und nicht am Einstiegspunkt.
- **Sicherheit:** PSA `restricted` und reine Namespace-Rechte reichen. **Befund:** Auf dem eingebetteten kube-router von K3s wirkte eine Default-Deny-NetworkPolicy ≥ 10 min nicht auf neu gestartete Pods, also auf jeden Kaltstart.
- **GitOps:** Ein Re-Apply läuft ohne Konflikte. `pingsource-mt-adapter` driftet aber dauerhaft. Argo CD G3 wurde nicht gemacht.

Bedingungen (als Follow-up-Vorschläge, keine Tickets angelegt):

1. GitOps-Drift und Laufzeitfelder lösen, Operator prüfen
2. TLS und Einstiegspunkt für ADR-010 entscheiden
3. NetworkPolicy auf dem Ziel-CNI nachtesten
4. Durable Eventing erst mit einer ADR-029-Entscheidung
5. KServe mit Knative 1.24 prüfen

Aufwand (Schätzung): 33–59 PT, ohne Durable Eventing 25–44 PT.

Report: `architecture/spikes/OK-211-knative-serverless/REPORT.md`, Management-Summary daneben. Branch `spike/OK-211-knative-serverless`. Die PR folgt nach Freigabe (CP2).
