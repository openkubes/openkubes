# Entwurf: Datenschutzerklärung für openkubes.org (nicht veröffentlicht)

> REVIEW REQUIRED. Technischer und rechtlicher Arbeitsentwurf. Nicht als fertige Datenschutzerklärung veröffentlichen, bevor die unten markierten Datenflüsse und Angaben durch Netzwerkmitschnitt, Hosting-Verträge und juristische Prüfung geklärt sind.

**Stand des Entwurfs:** 15. November 2026

## 1. Verantwortlicher

**Kubernauts GmbH**  
Im Mediapark 4C, 50670 Köln, Deutschland  
E-Mail: contact@kubernauts.de  
Telefon: +49 221 379 90 680

[Benennung eines Datenschutzbeauftragten und Kontaktdaten prüfen. Nicht ungeprüft die Rollenbezeichnung der anderen Website übernehmen.]

## 2. Grundsatz der Datensparsamkeit

OpenKubes stellt Informationen über das OpenKubes-Projekt bereit. Die Website soll ohne nicht notwendige Analyse- und Werbetechnologien funktionieren. Es ist beabsichtigt, keine Google Analytics-, Google Ads- oder LinkedIn-Tracking-Pixel einzusetzen. Die tatsächliche Implementierung muss auf jeder Route und im ausgelieferten Build überprüft werden. Es werden keine Aussagen über vollständige Trackingfreiheit getroffen, bevor diese Prüfung erfolgt ist.

## 3. Technische Bereitstellung und Server-Logs

Beim Abruf von Webseiten werden technisch notwendige Verbindungsdaten verarbeitet, etwa IP-Adresse, Abrufzeit, aufgerufene Ressource, Browser-/Geräteinformationen und HTTP-Status, soweit der jeweilige Hosting- bzw. CDN-Dienst diese Daten verarbeitet.

**Zwecke:** sichere Auslieferung, Stabilität, Fehleranalyse und Abwehr von Missbrauch.  
**Vorgesehene Rechtsgrundlage:** Art. 6 Abs. 1 lit. f DSGVO, nach Interessenabwägung zu bestätigen.  
**Dienstleister / Auftragsverarbeitung:** [tatsächliche GitHub-Pages-, DNS-, CDN- und Proxy-Konfiguration ermitteln, Anbieter benennen, Rollen und Verträge prüfen].  
**Speicherdauer:** [konkrete Logtypen, Fristen und Zugriffsrechte verifizieren].  
**Drittlandübermittlung:** [tatsächliche Anbieterstandorte, Übermittlungen und Rechtsgrundlagen prüfen].

## 4. Cookies, Browser-Speicherung und optionale Inhalte

Das Ziel ist, keine nicht notwendigen Cookies oder vergleichbaren Speicher-/Endgerätezugriffe einzusetzen. Für den Einsatz solcher Technologien sind neben Art. 6 DSGVO die Anforderungen aus § 25 TDDDG gesondert zu prüfen. Eine Einwilligungsoberfläche ist nur dann entbehrlich, wenn alle verbleibenden Technologien entsprechend eingeordnet und dokumentiert wurden.

[Browser-Audit mit frischem Profil für Cookies, localStorage, sessionStorage, IndexedDB, Service Workers und alle Drittanfragen durchführen.]

## 5. Ask OK AI Lite

Die derzeit geprüfte Datei `website/assets/ok-ai-lite-preview.js` implementiert feste, redaktionell freigegebene Antworten direkt im Browser. In dieser Datei wurden keine KI-Backend-Aufrufe, keine `fetch()`-Aufrufe und keine Speicherung in Cookies oder Browser-Storage festgestellt. Nutzereingaben werden in der laufenden Seitenansicht dargestellt. Die Implementierung weist darauf hin, keine Geheimnisse einzugeben.

**Hinweis:** Aussagen beziehen sich auf die geprüfte Lite-Datei. Vor Veröffentlichung ist zu bestätigen, dass tatsächlich nur diese Variante ausgeliefert wird und keine anderen Skripte Eingaben versenden oder speichern.

## 6. Externe Links und Medien

Die Website verlinkt auf externe Angebote, etwa GitHub, YouTube, Slack oder Meetup. Diese Anbieter können beim bewussten Öffnen der jeweiligen Links personenbezogene Daten nach eigenen Bedingungen verarbeiten.

Die OpenKubes-Homepage verwendet nach PR #490 statt des externen YouTube-Thumbnails eine lokal gerenderte CSS/HTML-Vorschau; der YouTube-Link wird erst nach Klick geöffnet. [Alle übrigen Seiten, Skripte, Fonts, eingebetteten Ressourcen und Vorschaubilder kontrollieren.]

## 7. Kontaktaufnahme

Beim Versand einer E-Mail an die Betreiberin werden die übermittelten Angaben zur Bearbeitung der Anfrage verarbeitet. Die Rechtsgrundlage richtet sich nach dem Anliegen, regelmäßig Art. 6 Abs. 1 lit. b oder lit. f DSGVO. [Mailhosting-Dienstleister, Zugriffsbefugnisse und konkrete Löschfristen prüfen.]

## 8. Betroffenenrechte

Im Rahmen der gesetzlichen Voraussetzungen bestehen insbesondere die Rechte auf Auskunft (Art. 15 DSGVO), Berichtigung (Art. 16), Löschung (Art. 17), Einschränkung der Verarbeitung (Art. 18), Datenübertragbarkeit (Art. 20) und Widerspruch (Art. 21). Sofern eine Verarbeitung auf Einwilligung beruht, kann diese mit Wirkung für die Zukunft widerrufen werden (Art. 7 Abs. 3 DSGVO). Betroffene können sich bei einer zuständigen Datenschutzaufsichtsbehörde beschweren.

## 9. Datensicherheit und Änderungen

Wir setzen geeignete technische und organisatorische Sicherheitsmaßnahmen ein. Diese Informationen werden bei Änderungen tatsächlicher Datenverarbeitung und Rechtsanforderungen aktualisiert.

## Veröffentlichungsblocker

- [ ] Hosting- und CDN-Anbieter sowie deren Verantwortlichkeiten verifiziert
- [ ] Auftragsverarbeitungsverträge / Drittlandtransfers / Transfergarantien geprüft
- [ ] Tatsächliche Protokoll- und E-Mail-Löschfristen belegt
- [ ] Vollständiger HAR-/Cookie-/Storage-Scan aller Seitentypen inkl. Vorschau-Domain
- [ ] Korrekte Angaben zu Datenschutzbeauftragtem und zuständiger Behörde
- [ ] Aussage zu Analytics/Tracking und Ask OK AI Lite gegen Build verifiziert
- [ ] DSGVO-/TDDDG-Rechtsprüfung und Freigabe dokumentiert
- [ ] EN-Übersetzung konsistent und rechtlich geprüft
- [ ] Erst dann öffentliche Seiten und Footer-Links ergänzen
