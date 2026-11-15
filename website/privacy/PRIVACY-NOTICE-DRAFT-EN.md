# Draft: Privacy Notice for openkubes.org (not published)

> **INTERNAL REVIEW REQUIRED — DO NOT PUBLISH.** Working English counterpart to the German draft. Hosting, logging, retention and international transfers remain to be verified before any public use.

**Draft dated:** 15 November 2026

## 1. Controller

**Kubernauts GmbH**  
Im Mediapark 4C, 50670 Köln, Germany  
Email: contact@kubernauts.de  
Phone: +49 221 379 90 680

[Verify whether a data protection officer is designated and, if applicable, publish the correct contact details. Do not assume that the managing director is automatically the DPO.]

## 2. Data minimization and website operation

The purpose of OpenKubes is to provide information, documentation, source references and community links for the OpenKubes project. The intended design does not include Google Analytics, Google Ads or LinkedIn marketing pixels.

**Runtime evidence:** A clean Chromium sample of `preview.openkubes.org/` and `preview.openkubes.org/ai/` on 15 November 2026 contacted only the Preview host (14 and 12 requests respectively). The tested pages set no observable cookies or local/session storage entries. This does **not** prove that every route or the production origin behaves identically.

## 3. Hosting and technical access logs

When pages are accessed, the infrastructure provider may process technical connection information such as IP address, timestamp, resource requested, browser/HTTP characteristics and status codes.

**Purposes:** secure, reliable delivery, troubleshooting and abuse prevention.  
**Possible lawful basis:** Article 6(1)(f) GDPR, subject to a documented balancing test.  
**Hosting:** Site publishing architecture identifies **GitHub Pages** for the production site and **Cloudflare Pages** for the separate Preview; confirm the actually operating infrastructure and any intermediary/CDN/DNS services.  
**Processors and international transfers:** [Confirm contractual roles, subprocessors, locations, applicable safeguards, and third-country transfer arrangements.]  
**Retention:** [Obtain and verify specific provider- and mail-service log retention periods or applicable criteria.]

## 4. Cookies and device storage

The goal is not to use non-essential cookies or comparable terminal-device storage. The Preview audit found zero cookies and zero local/session storage entries on its **two sampled routes**. Other routes, browsers, IndexedDB and non-blocked service workers require confirmation.

Whether consent controls are needed is assessed separately under § 25 TDDDG and the GDPR. No blanket claim of a cookie-free entire website should be published without verification.

## 5. Ask OK AI Lite

The reviewed Ask OK AI Lite implementation displays a small selection of fixed, curated documentation responses directly in the browser. It is **not** a live AI service or chatbot backend. The 15 November Preview audit submitted one predefined question and observed **zero additional network requests** during the interaction. Input was displayed in the current page and did not appear in the sampled browser storage counts. Visitors are asked not to enter secrets.

[Reconfirm that the production deployment uses the same reviewed Lite implementation and does not add data transmission or persistence.]

## 6. External links and media

The site may link visitors to independent third-party destinations such as GitHub, YouTube, Slack and Meetup; their privacy practices apply after visitors choose to open them.

The reviewed source replaces an automatically fetched YouTube thumbnail with a locally rendered preview and disables Google-hosted fonts in MkDocs Material. The sampled refreshed Preview browser audit did not contact these providers. [Inspect all remaining public routes and the deployed production origin.]

## 7. Contact by email

Messages sent to Kubernauts may be processed to reply and handle enquiries. Depending on the enquiry, applicable legal bases may include Article 6(1)(b) and/or (f) GDPR. [Verify email hosting, recipients, data categories, deletion rules and any processor arrangements.]

## 8. Individual rights and supervisory authority

Subject to statutory conditions, individuals have rights to access (Article 15 GDPR), rectification (Article 16), erasure (Article 17), restriction (Article 18), data portability (Article 20), and objection (Article 21). Consent, where used, can be withdrawn for the future (Article 7(3)). Individuals may complain to the competent data protection supervisory authority. [Verify the appropriate supervisory authority and contact details.]

## 9. Security and updates

The website operator applies technical and organizational measures appropriate to the processing and may update this notice when technology, providers or legal requirements change. [Confirm actual controls; avoid unsupported security guarantees.]

## Publication blockers

- [ ] Actual production/preview hosting, CDN/DNS, processors and transfer mechanisms confirmed
- [ ] Server and mail-log retention durations/criteria confirmed
- [ ] DPO/contact and supervisory authority details verified
- [ ] Wider-route production network, cookies, IndexedDB and service workers assessed
- [ ] Final factual consistency check against the German notice and Art. 13 GDPR
- [ ] Qualified legal review and explicit publication approval
- [ ] Only then add published DE/EN routes and footer links
