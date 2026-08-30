# Grundlagen für Informations- und Schulungsmaterialien zu KasselDIALOG

## Zweck dieses Dokuments

Dieses Dokument bündelt den bekannten Stand zu KasselDIALOG und legt fest,
welche Informations- und Schulungsmaterialien für die lokale SSF-Instanz in
Kassel benötigt werden. Es ist **keine fertige Nutzungsanleitung**. Es dient
als abgestimmte Arbeitsgrundlage für Redaktion, Schulung, Betrieb,
Datenschutz und Fachbereiche.

Die Materialien sollen den **angestrebten Zielzustand** vermitteln: eine
niedrigschwellige, selbstbestimmt betreibbare Infrastruktur für mehrsprachige
kommunale Gespräche. Sie dürfen daher über den heutigen technischen
Funktionsumfang hinausgehen. Für jede konkrete Veröffentlichung oder Schulung
muss jedoch erkennbar bleiben, ob eine Funktion bereits produktiv nutzbar,
geplant oder nur ein mögliches Zukunftsszenario ist.

Jedes daraus abgeleitete Material muss vor Veröffentlichung gegen die
tatsächlich ausgerollte KasselDIALOG-Version, die freigegebenen Prozesse und
die geltenden Datenschutzinformationen geprüft werden.

Operative Schritt-für-Schritt-Anleitungen dürfen ausschließlich produktiv
freigegebene Funktionen enthalten; Zielbildmaterial kennzeichnet noch nicht
verfügbare Funktionen eindeutig.

## Produkt in einem Satz

KasselDIALOG ist die gebrandete Kasseler Instanz von Smart Speech Flow (SSF).
Sie unterstützt zeitnahe mehrsprachige Gespräche zwischen einer betreuenden
Person und einer eingeladenen Gesprächspartnerin bzw. einem eingeladenen
Gesprächspartner – per Text und Audio.

## Zielzustand und heutiger Funktionsumfang

KasselDIALOG soll als wiederverwendbarer Baustein für mehrsprachige digitale
Kommunikation im öffentlichen Raum eingesetzt werden. Der Zielzustand ist ein
durchgängiger, browserbasierter Gesprächsfluss ohne Installation und ohne
komplexes Onboarding für die teilnehmende Person. Er unterstützt kommunale
Beratung und Verwaltung dort, wo fehlende gemeinsame Sprache Verfahren,
Beratung und Teilhabe erschwert.

Für den Zielzustand gehören dazu eine klare Trennung von Plattformbetrieb,
Mandantenverantwortung, operativer Gesprächsführung und teilnehmender Person;
sichere Einladungen; wählbare, freigegebene Sprachen; nachvollziehbare
Datenschutz- und Supportprozesse; sowie ein kontrollierter, möglichst
selbstbestimmter Betrieb der offenen Lösung.

### Heute und Zielbild sauber unterscheiden

Die Materialien dürfen nur Funktionen als verfügbar darstellen, die im
Kasseler Betrieb tatsächlich freigegeben sind.

| Heute im Session-Workflow abbildbar | Nicht als heutige Funktion zusagen |
| --- | --- |
| Operative Mitarbeitende starten und beenden Gespräche. | Umfassende Mandantenverwaltung, Selbstverwaltung von Benutzerkonten und Berechtigungen. |
| Einladungen werden per Link, Code oder QR-Code weitergegeben. | Plattformweite Administration, Reporting oder uneingeschränkter Supportzugriff auf Gesprächsinhalte. |
| Eingeladene Personen wählen eine Sprache, treten einer konkreten Sitzung bei und kommunizieren per Text oder Audio. | Dauerhafte Speicherung, Export oder Löschung von Gesprächsinhalten als frei verfügbare Selbstbedienungsfunktion. |
| Die Anwendung zeigt Verbindungs- und Gesprächsstatus. Eine sichtbare Feedback-Oberfläche ist bis zur Freigabe eines gespeicherten Feedbackprozesses nicht als Rückmeldeweg zu verwenden. | Eine bestimmte Übersetzungsqualität, Verfügbarkeit oder Unterstützung jeder Sprache ohne vorherige Freigabe. |

Die Rollen `system_admin` und `tenant_admin` sind in der
Projektarchitektur ein Zielbild. Für den derzeitigen Session-Workflow sind
vor allem die Rollen **operativer Admin** (Gespräch führende Person) und
**Customer** (eingeladene Gesprächspartnerin bzw. eingeladener
Gesprächspartner) relevant.

### Zielbild für Schulungsinhalte

| Zielzustand | Bedeutung für die Schulungsmaterialien |
| --- | --- |
| Kommunale Gesprächsinfrastruktur | Beispiele richten sich an Verwaltung, Beratungsstellen, Stadtteil- und Familienzentren sowie vergleichbare Einrichtungen aus. |
| Browserbasierter Zugang | Teilnehmenden-Material erklärt Link oder QR-Code, Sprache und Mikrofon ohne Installationsanleitung. |
| Durchgängiger Gesprächsfluss | Schulungen zeigen Sprache und Text als Gesprächshilfe, nicht als Folge isolierter Übersetzungsbefehle. |
| Inklusive Nutzung | Materialien funktionieren auch für Erstnutzende und Personen mit geringer Technikaffinität: einfache Sprache, kurze Schritte und Unterstützung vor Ort. |
| Vier klar abgegrenzte Rollen | Materialien für den Ausbau berücksichtigen System-Admin, Mandanten-Admin, operativen Admin und Customer mit ihren jeweiligen Grenzen. |
| Selbstbestimmt betreibbare Open-Source-Lösung | Leitungs-, IT- und Datenschutzmaterial erklärt Nachnutzung, offene Schnittstellen, nachvollziehbare Datenflüsse und Betriebsverantwortung. |
| Kontrollierte Weiterentwicklung | Neue Sprachen, Modelle, Integrationen und Aufbewahrungsfunktionen werden erst nach fachlicher, technischer und datenschutzrechtlicher Freigabe geschult. |

## Zielgruppen und Lernziele

| Zielgruppe | Nach der Information bzw. Schulung kann die Person … | Geeignete Formate |
| --- | --- | --- |
| Operative Mitarbeitende | ein Gespräch sicher vorbereiten, starten, begleiten, beenden und einfache Störungen beheben. | Kurzanleitung, Präsenz-/Online-Schulung, Übungsszenario, Fehlerhilfe. |
| Eingeladene Gesprächspartner:innen | einer Einladung beitreten, Sprache wählen, Mikrofon freigeben und Text bzw. Sprache nutzen. | mehrsprachige Teilnehmenden-Karte, QR- oder Link-Landingpage, kurze Vor-Ort-Erklärung. |
| Lokale Multiplikator:innen und fachlich Verantwortliche | Einsätze vorbereiten, Kolleg:innen einweisen, Rückmeldungen bündeln und an den Support eskalieren. | Multiplikator:innen-Leitfaden, Schulungsskript, Freigabe- und Eskalationsübersicht. |
| IT, Betrieb und Support | Zuständigkeiten, Diagnosegrenzen, Incident- und Kommunikationswege kennen. | interner Supportleitfaden, Runbook-Verweise, Kontaktliste. |
| Datenschutz und Leitung | Zweck, Datenflüsse, Einwilligungstexte, Freigaben und Risiken bewerten. | Datenschutz-Steckbrief, Freigabecheckliste, Versionierungsprotokoll. |
| Leitung und Digitalstrategie | Einsatznutzen, Nachnutzung, digitale Souveränität und Voraussetzungen für einen nachhaltigen Betrieb beurteilen. | Entscheidungsunterlage, Management-Briefing, Betriebs- und Nachnutzungskonzept. |

## Benötigtes Materialpaket

### Priorität 1: Für den kontrollierten Start

1. **KasselDIALOG-Steckbrief (eine Seite)**
   - Ziel und Nutzen in einfacher Sprache
   - Zielgruppen und zulässige Einsatzszenarien
   - Voraussetzungen: geeignetes Endgerät, Internet, ruhige Gesprächssituation
   - Verweis auf Datenschutzinformation und lokalen Support

2. **Kurzanleitung für operative Mitarbeitende**
   - Anmeldung ausschließlich über den freigegebenen Zugang
   - Gespräch starten
   - Einladungslink, Code oder QR-Code sicher weitergeben
   - Warten, bis die eingeladene Person beigetreten ist
   - Text und Audio verwenden
   - für gute Verständlichkeit: deutlich und in kurzen Abschnitten sprechen;
     Hintergrundgeräusche nach Möglichkeit vermeiden
   - Gespräch ordentlich beenden
   - Was bei einem laufenden Gespräch passiert, wenn ein neues begonnen wird

3. **Teilnehmenden-Karte in einfacher, mehrsprachig adaptierbarer Sprache**
   - QR-Code oder Link öffnen
   - Sprache auswählen
   - Hinweise zur Einwilligung bzw. Datenverarbeitung lesen
   - Mikrofon im Browser erlauben, falls Sprache genutzt werden soll
   - Sprechen oder schreiben
   - in kurzen, klaren Sätzen sprechen; bei Bedarf die betreuende Person um
     Wiederholung oder Unterstützung bitten
   - Hilfe bei Problemen: an die betreuende Person wenden

4. **Schulungsskript mit Demo und Übung**
   - 30–45 Minuten, inklusive vollständigem Musterablauf
   - Rollenübung mit Mitarbeitenden und Teilnehmenden-Perspektive, darunter
     mindestens eine erstnutzende Person ohne besondere Technikkenntnisse
   - Übung zu Mikrofonfreigabe und Unterbrechung der Verbindung
   - Übung mit klarer Sprache, kurzen Redeabschnitten und einer bewusst
     geräuschvollen Umgebung, um die Gesprächsregeln nachvollziehbar zu machen
   - Abschlusscheck: Jede teilnehmende Person startet und beendet ein
     Testgespräch selbstständig

5. **Fehlerhilfe für den Einsatz**
   - Mikrofon wird nicht erkannt oder Berechtigung wurde abgelehnt
   - Link, Code oder QR-Code funktioniert nicht
   - Gesprächspartner:in ist noch nicht verbunden
   - Verbindung ist unterbrochen
   - Übersetzung ist unklar: Aussage wiederholen, kürzer und deutlicher
     sprechen, Hintergrundgeräusche verringern oder auf Text wechseln
   - Nachricht kann noch nicht gesendet werden
   - Gespräch wurde beendet oder es wird versehentlich ein neues Gespräch
     gestartet
   - Wann ein Fall an den lokalen Support geht

### Priorität 2: Für nachhaltigen Betrieb

6. **Leitfaden für Multiplikator:innen und lokale Verantwortliche**
   - Einweisung neuer Mitarbeitender
   - Einsatzvoraussetzungen und Raum-/Gerätecheck
   - Pflege der lokalen Kontakt- und Eskalationsliste
   - Sammeln von Feedback und wiederkehrenden Problemen
   - Beobachtung realer Nutzung: Welche Schritte benötigen Erklärung, welche
     Sprachen und Geräte werden eingesetzt, wo entstehen Verständigungs- oder
     Technikprobleme?
   - Regelmäßige Auffrischungsschulungen

7. **Datenschutz- und Einsatzleitfaden**
   - verbindlicher, freigegebener Zweck der Verarbeitung
   - Verhalten bei sensiblen oder besonders schutzwürdigen Inhalten
   - aktuell gültiger Einwilligungs- und Aufbewahrungsprozess
   - Verhalten bei Auskunfts-, Lösch- oder Beschwerdeanfragen
   - keine Zugangsdaten, geheimen Links oder Gesprächsinhalte in
     Schulungsunterlagen, Tickets oder ungeschützten Kanälen teilen

8. **Feedback- und Auswertungsbogen**
   - Verständlichkeit und tatsächlicher Nutzen
   - technische Hürden (insbesondere Mikrofon, Browser und Netz)
   - Umgang mit Sprachen und Gesprächssituationen
   - offene Verbesserungsvorschläge
   - datensparsame Erhebung ohne Gesprächsinhalte

9. **Zielbild- und Entscheidungsunterlage für Leitung, IT und Datenschutz**
   - kommunale Einsatzfelder und erwarteter Nutzen: schnellere Verständigung,
     weniger Medienbrüche und besserer Zugang zu Beratung und Verwaltung
   - Open-Source- und Nachnutzungsperspektive: kein Black-Box-Dienst,
     nachvollziehbare Architektur und gestaltbare Betriebsverantwortung
   - Optionen für kontrollierten Eigenbetrieb, On-Premises- oder Hybridbetrieb
     nach lokaler Sicherheits- und Datenschutzprüfung
   - Ausbaupfad: Mandantenverwaltung, Rollen, Sprachen, Modelle,
     Integrationen, Audit- und Datenschutzfunktionen

## Empfohlener Schulungsablauf

| Abschnitt | Dauer | Ergebnis |
| --- | ---: | --- |
| Einordnung und Einsatzgrenzen | 5 Minuten | Die Teilnehmenden wissen, wann KasselDIALOG eingesetzt werden darf. |
| Datenschutz und Gesprächsregeln | 5 Minuten | Sensible Inhalte und Einwilligungen werden bewusst behandelt. |
| Live-Demonstration | 10 Minuten | Der gesamte Ablauf ist sichtbar. |
| Praktische Übung in Zweiergruppen | 10–15 Minuten | Jede Person probiert beide Rollen aus. |
| Fehlerfälle und Support | 5–10 Minuten | Die Teilnehmenden können häufige Störungen einordnen und eskalieren. |
| Abschluss und Feedback | 5 Minuten | Offene Fragen und Verbesserungsbedarf sind erfasst. |

Als Beispielszenarien eignen sich kurze, alltagsnahe Verwaltungsgespräche,
etwa ein Termin-, Beratungs- oder Orientierungsgespräch. Reale
personenbezogene Daten dürfen in Schulungen nur nach ausdrücklicher Freigabe
verwendet werden; vorzugsweise werden fiktive Beispiele eingesetzt.

Die Übungsszenarien sollen unterschiedliche reale Voraussetzungen abbilden:

- zwei Gesprächspartner:innen mit zwei Geräten;
- ein Gespräch mit Audio- und Textwechsel;
- eine Person, die KasselDIALOG zum ersten Mal nutzt und Unterstützung beim
  Link, der Sprachwahl oder der Mikrofonfreigabe braucht;
- eine unterbrochene oder schwache Netzwerkverbindung mit Wiederbeitritt;
- ein Gespräch mit Umgebungsgeräuschen, bei dem die Beteiligten die
  Gesprächsregeln anwenden;
- ein sensibler Beratungsfall, in dem geklärt wird, ob KasselDIALOG genügt
  oder eine qualifizierte Sprachmittlung erforderlich ist.

Ein-Gerät-, mobile oder kioskartige Szenarien sind als Zielbild und für
Erprobungen wertvoll, dürfen aber nur dann als regulärer Ablauf geschult
werden, wenn sie für die Kasseler Produktionsinstanz freigegeben sind.

## Kommunale Einsatzkontexte und Nutzenkommunikation

Die Informationsmaterialien sollen KasselDIALOG nicht als isoliertes
KI-Werkzeug darstellen, sondern als Infrastruktur für verständliche
Kommunikation. Geeignete, vorbehaltlich lokaler Freigabe ausgestaltete
Einsatzkontexte sind beispielsweise:

- Beratungs- und Orientierungsgespräche mit Bürger:innen;
- Gespräche in Stadtteil- und Familienzentren;
- kontaktintensive Verwaltungsleistungen mit Sprachbarrieren;
- vergleichbare gemeinwohlorientierte Einrichtungen.

Die Kernbotschaft für Mitarbeitende lautet: KasselDIALOG kann Gespräche ohne
gemeinsame Sprache erleichtern und damit Wartezeiten, Rückfragen und
Medienbrüche verringern. Es ersetzt weder fachliche Verantwortung noch eine
erforderliche qualifizierte Sprachmittlung in Situationen, in denen diese
rechtlich oder fachlich vorgeschrieben ist.

Für Leitung und IT ergänzt die Kommunikation: Offener Quellcode, modulare
Komponenten und dokumentierte Schnittstellen ermöglichen Nachnutzung,
Prüfbarkeit und kontrollierte Weiterentwicklung. Dies ist ein
Gestaltungs- und Betriebsversprechen, keine Zusage, dass jede Kommune ohne
eigenen Einführungs-, Sicherheits- und Supportaufwand sofort produktiv starten
kann.

## Kernbotschaften für alle Materialien

- KasselDIALOG unterstützt Verständigung, ersetzt aber nicht das fachliche
  Urteil der beteiligten Personen.
- Die Einladung gilt für eine konkrete Gesprächssitzung und ist nur mit der
  vorgesehenen Person zu teilen.
- Für Sprachkommunikation muss das Mikrofon im Browser freigegeben sein.
- Deutlich, in kurzen Abschnitten und möglichst bei geringer
  Hintergrundlautstärke sprechen; bei Unklarheiten wiederholen oder Text
  verwenden.
- Ein stabiler Internetzugang und eine möglichst ruhige Umgebung verbessern
  die Nutzbarkeit.
- Die Anwendung zeigt an, ob die Verbindung hergestellt, unterbrochen oder
  das Gespräch beendet ist.
- Bei kritischen fachlichen, datenschutzrechtlichen oder technischen Fragen
  wird das Gespräch nicht improvisiert fortgesetzt, sondern der definierte
  lokale Prozess genutzt.

## Pilotierung, Feedback und laufende Verbesserung

KasselDIALOG soll in realen kommunalen Gesprächssituationen weiterentwickelt
werden. Schulungsmaterial ist daher kein einmaliges Ergebnis, sondern wird
aus den Erfahrungen im Einsatz fortgeschrieben.

Nach jeder Pilot- oder Schulungsphase werden mindestens folgende Fragen
datensparsam ausgewertet:

- Konnten Admin und Customer den Gesprächsablauf ohne dauerhafte technische
  Begleitung bewältigen?
- Waren Einladung, Sprachwahl, Mikrofonfreigabe und Statusanzeigen
  verständlich?
- Wann war Audio sinnvoll, wann Text?
- Welche Rolle spielten Gerät, Netzqualität, Umgebungsgeräusche und
  Technikaffinität?
- Welche Sprachkombinationen, Begriffe oder Gesprächssituationen benötigen
  zusätzliche Vorbereitung oder ein Glossar?
- Gab es Situationen, in denen die Anwendung nicht eingesetzt werden sollte
  oder eine qualifizierte Sprachmittlung notwendig war?

Die Auswertung trennt Probleme des Gesprächsablaufs, der Technik, der
Übersetzungsqualität und des lokalen Einsatzprozesses. Gesprächsinhalte und
personenbezogene Daten werden dabei nicht unnötig in Feedbackbögen oder
Schulungsdokumentation übernommen.

## Datenschutz- und Sicherheitsprüfung vor Veröffentlichung

Die derzeitigen Quellen enthalten unterschiedliche Aussagen zur
Aufbewahrung: Die Nutzungsoberfläche beschreibt eine Verarbeitung von Audio
und Transkript während der aktiven Sitzung mit optionaler Einwilligung zur
Speicherung für bis zu 180 Tage; technische Dokumentation beschreibt für
Original-Audiodateien eine 24-Stunden-Löschfrist. Diese Angaben dürfen nicht
unaufgelöst in externe Informationsmaterialien übernommen werden.

Vor Freigabe muss die zuständige Stelle schriftlich bestätigen:

1. welche Daten die Kasseler Produktionsinstanz verarbeitet und speichert;
2. welche Aufbewahrungsfristen dort tatsächlich gelten;
3. ob und wie eine optionale Einwilligung technisch wirksam gespeichert wird;
4. welche Datenschutzinformation, Kontaktstelle und Eskalationswege gelten;
5. welche Sprachen, Browser, Endgeräte und Einsatzorte freigegeben sind.

Bis zu dieser Bestätigung verwenden Materialien ausschließlich die
freigegebene Datenschutzerklärung und treffen keine detaillierten Aussagen
über Speicherfristen.

## Redaktions- und Freigabeprozess

1. Fachbereich benennt Einsatzszenarien, Zielgruppen und lokale
   Ansprechpersonen.
2. Redaktion trennt in jedem Material sichtbar **Zielbild**, **bereits
   verfügbare Funktionen** und **noch nicht freigegebene Ausbauschritte**.
3. Betrieb bestätigt den produktiven Funktionsumfang, Zugangsweg und
   Supportprozess.
4. Datenschutz prüft Texte zu Einwilligung, Speicherung, Aufbewahrung und
   Betroffenenrechten.
5. Redaktion erstellt die fünf Materialien der Priorität 1 aus dieser
   Grundlage.
6. Zwei bis drei typische Anwender:innen testen Verständlichkeit und Ablauf
   anhand eines Testgesprächs.
7. Fachbereich, Betrieb und Datenschutz geben die jeweilige Version frei.
8. Jede veröffentlichte Datei erhält Version, Datum, verantwortliche Stelle
   und einen Überprüfungstermin.

## Offene Entscheidungen vor der Ausarbeitung

- Welche konkreten Stellen und Gesprächsanlässe starten mit KasselDIALOG?
- Wer ist lokaler First-Level-Support und wer übernimmt technische
  Eskalationen?
- Welche Sprachen und Geräte werden zum Start unterstützt?
- Welche Version der Datenschutzinformation und welche Einwilligung gelten
  produktiv?
- In welchen Sprachen werden Teilnehmenden-Karte und Einwilligungstexte
  benötigt?
- Wie werden Mitarbeitende geschult, dokumentiert und regelmäßig
  nachgeschult?
- Nach welchen Kriterien wird der Pilot bewertet und über einen breiteren
  Rollout entschieden?

## Weiterführende interne Quellen

- [Session-Lebenszyklus](../architecture/session-flow.md)
- [Customer Journey und Rollenübergaben](../architecture/customer-journey.md)
- [Rollen- und Berechtigungsmodell](../architecture/roles-and-permissions.md)
- [Manuelle Audio-Testcheckliste](../testing/AUDIO_RECORDING_MANUAL_TEST_CHECKLIST.md)
- [Frontend-API-Leitfaden](frontend_api.md)
- [Datenschutz- und Sicherheitsleitlinien für die Bereitstellung](../deployment/SECURITY.md)
- [Wettbewerbsbeschreibung KasselDIALOG](https://open-source-wettbewerb.de/voting/kasseldialog/)
- [Smart Kassel: sozial-digitale Ankerorte](https://www.kassel.de/einrichtungen/smartkassel/leitprojekte/udp-1/index.php)
- [Smart Speech Flow: Kasseler Projektbroschüre](https://www.kassel.de/einrichtungen/smartkassel/smart-stories.php.media/190148/Smart-Speech-Flow.pdf)
- [Produktvision](../PRODUCT_VISION.md)
- [User-Testing-Strategie](../testing/USER_TESTING_STRATEGY.md)
