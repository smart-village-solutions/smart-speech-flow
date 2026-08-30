# Product Roadmap

## Vom MVP zur Vision

Dieses Dokument beschreibt den produktstrategischen Weg von Smart Speech Flow vom heutigen MVP hin zur angestrebten Vision einer offenen und souveraen betreibbaren Infrastruktur fuer mehrsprachige Echtzeitgespraeche.

Es ist bewusst keine rein technische Feature-Liste. Die Roadmap priorisiert danach, was den groessten Produktwert schafft, was Risiken reduziert und was Smart Speech Flow als Produkt und Plattform glaubwuerdig macht.

## Ausgangspunkt: Heutiger MVP

Der aktuelle Stand von Smart Speech Flow ist ein funktionsfaehiges MVP mit echtem Produktkern:

- sessionbasierte Kommunikation zwischen zwei Rollen
- Audio-, Text-, Uebersetzungs- und TTS-Pipeline
- WebSocket-basierter Echtzeitfluss
- Docker-basierter Betrieb auf eigener Infrastruktur
- Monitoring, Health Checks und grundlegende Betriebsfaehigkeit
- erste Frontend-Oberflaeche fuer Standalone-Nutzung

Der MVP beweist, dass der zentrale Use Case funktioniert. Gleichzeitig zeigt er typische MVP-Muster:

- viel Produktlogik liegt im API-Gateway
- einige Kernmodule sind sehr gross und wartungsintensiv
- die Plattformfaehigkeit ist vorhanden, aber noch nicht klar genug als Produktangebot ausformuliert
- der Standalone-Flow ist erkennbar, aber noch nicht durchgaengig auf operative Nutzung optimiert

## Strategische Leitidee

Der Weg zur Vision verlaeuft nicht ueber moeglichst viele KI-Features, sondern ueber vier aufeinander aufbauende Reifeschritte:

1. Den Kern-Use-Case robust machen
2. Das Produkt fuer den realen Einsatz vereinfachen
3. Die Plattform gezielt fuer Einbettung und Nachnutzung oeffnen
4. Den Betrieb in Verbund- und Partnerstrukturen skalierbar machen

## Was zuerst zaehlt

In dieser Phase sind nicht die meisten Features entscheidend, sondern die richtigen:

- Verlaesslichkeit im Gespraechsfluss
- einfache Inbetriebnahme und Nutzung
- nachvollziehbares Verhalten in Grenzfaellen
- sauberer Produktzuschnitt zwischen Standalone und Embedded
- glaubwuerdige Souveraenitaet im Betrieb

## Querschnittsthema: Nutzerforschung und Validierung

Der Weg vom MVP zur Vision darf nicht nur technisch gesteuert werden. Smart Speech Flow braucht frueh und wiederholt echtes Lernen mit realen Nutzenden.

Deshalb laeuft ueber mehrere Phasen hinweg ein eigener Validierungsstrang mit:

- umfangreichem Testing mit realen Nutzerinnen und Nutzern in echten oder realitaetsnahen Gespraechssituationen
- systematischer Erfassung von Anforderungen, Friktionen und Abbruchgruenden
- Vergleich unterschiedlicher Modelle fuer ASR, Uebersetzung und TTS
- Testing verschiedener Settings und Konfigurationen fuer Qualitaet, Geschwindigkeit und Stabilitaet
- Auswertung, welche Interaktionsmuster in welchen Szenarien wirklich funktionieren

Das Ziel ist nicht nur, Fehler zu finden, sondern Produktentscheidungen belastbar zu machen.

## Querschnittsthema: Strategische Innovationsfelder bewerten

Mit wachsender Produktreife entstehen neue Ideen fuer Interaktion, Wissen, Einbettung und Betriebsmodelle. Diese Ideen sind wertvoll, aber nicht jede gute Idee sollte sofort umgesetzt werden.

Deshalb ist auch die strukturierte Beurteilung moeglicher Erweiterungen Teil der Roadmap.

Zu diesen Innovationsfeldern gehoeren unter anderem:

- unterschiedliche Conversation Modes, zum Beispiel Zwei-Geraete-, Ein-Geraet-, Kiosk- oder Text-first-Szenarien
- adaptive Interaktionsmuster wie Auto-Aufnahme, Sprecherwechsel-Unterstuetzung oder vereinfachte Bedienmodi
- verschiedene UI-Typen, von responsiver Web-Oberflaeche bis zu app-nahen oder nativen Clients
- confidence-aware UX, also sichtbarer Umgang mit Unsicherheit in Transkription und Uebersetzung
- wissensgestuetzte Uebersetzung und kontextangereicherte Gespraechsunterstuetzung
- domainenspezifische Konfigurationspakete, Glossare und vorkonfigurierte Betriebsprofile

Diese Ideen werden nicht nach Neuheitsgrad priorisiert, sondern nach einem klaren Bewertungsraster:

- Loest die Idee ein reales, haeufiges Problem in wichtigen Gespraechssituationen?
- Verbessert sie das Gelingen des Gespraechs merklich?
- Erhoeht sie Verstaendlichkeit, Geschwindigkeit oder Vertrauen?
- Ist sie betreibbar, erklaerbar und integrierbar?
- Passt sie zur Vision einer offenen Gespraechsinfrastruktur oder lenkt sie davon ab?

Der Anspruch der Roadmap ist deshalb doppelt:

- gute Ideen sichtbar und pruefbar machen
- nur die Ideen in Produktentwicklung ueberfuehren, die ihren Wert im Einsatz wirklich belegen

## Phase 1: MVP stabilisieren

### Produktziel

SSF soll als spezialisiertes Gespraechsprodukt in realen Nutzungssituationen stabil funktionieren, bevor die Plattformbreite ausgebaut wird.

### Was in dieser Phase Prioritaet hat

- Harter Fokus auf die Qualitaet des Session- und Nachrichtenflusses
- robuste Audio-Verarbeitung auch bei unguenstigen Eingaben und Netzsituationen
- klare Fehlermeldungen und nachvollziehbare Statuszustaende fuer beide Gespraechsseiten
- Bereinigung technischer Schulden in den Kernmodulen des API-Gateways
- Teststabilitaet fuer die kritischen Produktpfade
- erste strukturierte Tests mit realen Nutzenden statt ausschliesslich technischer Validierung
- systematische Erfassung von Anforderungen aus Pilotierungen und Bedienbeobachtungen
- Baseline-Vergleiche fuer Modelle und Konfigurationen, um spaetere Produktentscheidungen nicht aus dem Bauch zu treffen

### Konkrete Outcomes

- Admin und Customer koennen ein Gespraech verlaesslich starten, fuehren und beenden
- Nachrichtenverlust, haengende Sessions und schwer erklaerbare WebSocket-Zustaende werden deutlich reduziert
- der Produktkern wird so stabil, dass Pilotierungen nicht vom Team eng begleitet werden muessen
- es entsteht ein belastbares Bild davon, welche Probleme technisch und welche Probleme wirklich nutzungsbedingt sind

### Was bewusst noch nicht im Fokus steht

- breite Erweiterung um neue KI-Funktionen
- grosse API-Flaechenerweiterung
- tiefe Mandanten- oder Abrechnungslogik

## Phase 2: Standalone-Produkterlebnis schliessen

### Produktziel

SSF soll als eigenstaendige Anwendung ohne Erklaerungsaufwand einsetzbar sein.

### Warum diese Phase wichtig ist

Ein Produkt, das nicht alleine gut funktioniert, wird spaeter auch schwer als Plattformbaustein vermittelbar. Standalone ist kein Nebenpfad, sondern der Referenzfall fuer Qualitaet, Bedienbarkeit und Vertrauensaufbau.

### Was in dieser Phase Prioritaet hat

- durchgaengige User Journey von Session-Erstellung bis Gespraechsabschluss
- bessere mobile Nutzbarkeit und resiliente Audio-Aufnahme
- klare Rollenfuehrung fuer Admin und Customer
- saubere Darstellung von Sprachstatus, Uebersetzungsstatus und Verbindungsstatus
- besseres Handling fuer Wiederbeitritt, Unterbrechungen und Timeout-Faelle
- verschiedene UI-Formen fuer unterschiedliche Nutzungskontexte, zum Beispiel Web-Oberflaeche, mobil optimierte Nutzung und spaeter App-nahe Erlebnisse
- ein explizites Nutzungsszenario mit zwei Gespraechspartnern an nur einem Geraet
- Auto-Aufnahme und aehnliche Interaktionsmuster zur Beschleunigung des Gespraechsflusses
- gezielte Nutzertests fuer Bedienbarkeit, Verstaendlichkeit und Gespraechsdynamik

### Konkrete Outcomes

- eine Organisation kann SSF als fertige Loesung zeigen, pilotieren und intern betreiben
- der Nutzen ist fuer nicht-technische Stakeholder sofort verstehbar
- das Produkt wirkt nicht mehr wie ein Technik-MVP, sondern wie ein einsatzfaehiger Service
- SSF kann nicht nur im Idealbild von zwei Endgeraeten, sondern auch in pragmatischen Vor-Ort-Szenarien sinnvoll genutzt werden

## Phase 3: Embedded-Faehigkeit gezielt ausbauen

### Produktziel

SSF soll nicht nur nutzbar, sondern integrierbar werden.

### Warum diese Phase kritisch ist

Die Vision von SSF lebt davon, dass es sowohl direkt eingesetzt als auch in andere Angebote eingebettet werden kann. Das verlangt mehr als vorhandene Endpunkte. Es braucht ein bewusstes Plattformdesign.

### Was in dieser Phase Prioritaet hat

- klare Trennung von Core-Gespraechslogik und Praesentationsschicht
- konsistente, dokumentierte und stabilisierte APIs fuer Session-, Message- und Event-Flows
- belastbare WebSocket- und Fallback-Schnittstellen fuer Fremdfrontends
- SDK-nahe Integrationspfade oder Referenzclients
- Konfigurierbarkeit fuer Branding, Deployment-Kontext und Integrationsszenarien
- klar definierte Varianten fuer unterschiedliche Oberflaechen und Integrationsarten
- saubere Unterstuetzung fuer alternative Clients, inklusive app-naher oder nativer Oberflaechen
- erste Integrationsmuster fuer Wissensdatenbanken oder kontextgebende Informationsquellen zur Verbesserung von Uebersetzungs- und Antwortqualitaet

### Konkrete Outcomes

- Portale und Fachverfahren koennen SSF als Sprachfunktion integrieren, ohne die komplette Logik selbst nachzubauen
- Integrationspartner sehen SSF als Capability und nicht nur als Demo-Oberflaeche
- das Produkt wird anschlussfaehig fuer White-Label-, OEM- und Plattformmodelle
- kontextangereicherte Gespraeche werden moeglich, wenn Organisationen relevante Wissensquellen anbinden wollen

## Phase 4: Betriebs- und Betreiberfaehigkeit professionalisieren

### Deliberately brought-forward foundation

Before the wider Phase-4 scope, SSF will implement a deliberately narrow
Control Plane Foundation because real operator and tenant pilots require a
safe administrative boundary. This includes tenant provisioning, root and
tenant-local identity separation, an initial tenant administrator,
tenant-local user and role administration, auditable and idempotent
reconciliation, readiness, and the SSF plugin's minimal configuration
contract with Studio.

This foundation is not deep enterprise administration. It does not include
ClickHouse or session-data analytics, usage or cost reporting, billing,
conversation-content access, regular support access, or full export and
deletion workflows. Phase 1 and Phase 2 retain priority for reliable
conversation flows and a simple standalone experience.

### Produktziel

SSF soll in gemeinsamen Betreiber- und Partnerstrukturen wirtschaftlich und organisatorisch tragfaehig werden.

### Was in dieser Phase Prioritaet hat

- Betriebsmodelle fuer einzelne Organisationen und geteilte Instanzen
- Governance fuer Rollen, Zugaenge, Verantwortlichkeiten und Supportgrenzen
- nutzungsnahe Metriken fuer Betrieb, Service und spaetere Kostenbeteiligung
- Security-, Audit- und Retention-Funktionen fuer ernsthafte Einsatzumfelder
- klarer Upgrade-, Release- und Supportpfad fuer selbst betriebene Instanzen
- reproduzierbare Test- und Benchmark-Setups fuer Modellwahl, Konfigurationsprofile und Deployment-Varianten

### Konkrete Outcomes

- eine Stadt, ein Traeger oder ein Betreiber kann eine Instanz nicht nur fuer sich selbst, sondern auch fuer Partner anbieten
- Betrieb und Nutzung werden organisatorisch steuerbar und fair verrechenbar
- SSF wird vom Projekt zu einem belastbaren Infrastrukturangebot
- Modell- und Konfigurationsentscheidungen werden transparent, messbar und betreibbar statt nur ad hoc getroffen

## Phase 5: Domainenreife und Oekosystem

### Produktziel

SSF soll sich von einer allgemeinen Loesung fuer sprachuebergreifende Gespraeche zu einem Standardbaustein fuer konkrete Einsatzkontexte entwickeln.

### Was in dieser Phase Prioritaet hat

- domainenspezifische Konfigurationen und Sprachsets
- Integrationen in reale Prozessketten statt isolierter Gespraeche
- ausbaubare Partner- und Betreiberstrukturen
- Referenzimplementierungen fuer typische Einsatzfelder
- wissensgestuetzte Gespraechsunterstuetzung durch angebundene Wissensdatenbanken, Glossare oder domanenspezifische Inhaltsquellen
- feinere Optimierung von Modellen und Settings je nach Einsatzfeld, Sprache und Betriebsziel

### Konkrete Outcomes

- SSF wird leichter nachnutzbar, weil typische Muster schon vorgedacht sind
- die Plattform gewinnt an Glaubwuerdigkeit und sinkenden Einfuehrungskosten
- das Produkt bewegt sich vom einzelnen Pilot zum wiederholbaren Rollout-Modell
- Gespraeche werden in spezialisierten Kontexten nicht nur uebersetzt, sondern inhaltlich belastbarer und konsistenter unterstuetzt

## Priorisierungslogik

Wenn Entscheidungen knapp werden, sollte Smart Speech Flow nach dieser Reihenfolge priorisieren:

1. Gespraech gelingt oder scheitert
2. Betrieb ist stabil oder fragil
3. Nutzung ist einfach oder erklaerungsbeduerftig
4. Integration ist klar oder individuell teuer
5. Zusatzfeatures sind nett oder wirklich strategisch notwendig

Das bedeutet konkret:

- lieber Session- und Verbindungsqualitaet verbessern als neue KI-Spielereien einbauen
- lieber echte Nutzerbeobachtung und saubere Anforderungserfassung betreiben als Produktannahmen intern zu romantisieren
- lieber Modelle und Konfigurationen systematisch vergleichen als sich frueh auf technische Lieblingsloesungen festzulegen
- lieber Innovationshypothesen strukturiert pruefen als attraktive Ideen vorschnell in den Kern zu ziehen
- lieber klare Integrationsschnittstellen schaffen als zu frueh viele Sonderfaelle im Frontend loesen
- lieber observability, Release-Disziplin und Supportfaehigkeit ausbauen als vorschnell in Feature-Breite gehen

## Strategische Nicht-Ziele

Um die Vision zu erreichen, sollte SSF einige Fallen bewusst vermeiden:

- kein allgemeiner Verwaltungsassistent werden wollen
- kein unstrukturiertes Sammelbecken fuer beliebige KI-Features werden
- nicht zu frueh komplexe Enterprise-Verwaltung bauen, bevor der Produktkern stabil ist
- die Plattform nicht auf Kosten des Standalone-Erlebnisses denken
- Embedded nicht nur als technische API-Existenz missverstehen

## Messbare Reifezeichen auf dem Weg

SSF bewegt sich glaubwuerdig in Richtung Vision, wenn folgende Fragen zunehmend mit Ja beantwortet werden koennen:

- Koennen zwei Personen ohne technische Begleitung ein Gespraech erfolgreich fuehren?
- Kann eine Organisation SSF selbst betreiben und sicher aktualisieren?
- Kann ein externes Frontend SSF nutzen, ohne interne Produktlogik duplizieren zu muessen?
- Kann ein Betreiber mehrere Nutzungskontexte organisatorisch sauber abbilden?
- Wirkt SSF fuer Partner wie ein verlaesslicher Baustein statt wie ein interessantes Experiment?
- Werden neue Ideen nicht nur gesammelt, sondern nachvollziehbar getestet, bewertet und priorisiert?

## Nordstern fuer die Produktsteuerung

Jede groessere Produktentscheidung sollte an einer einfachen Frage gemessen werden:

Macht diese Entscheidung es wahrscheinlicher, dass wichtige Gespraeche trotz Sprachbarriere sofort, verlaesslich und anschlussfaehig gefuehrt werden koennen?

Wenn die Antwort nicht klar Ja ist, sollte die Prioritaet hinterfragt werden.
