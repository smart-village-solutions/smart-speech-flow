# User Testing Strategy

## Zweck

Dieses Dokument beschreibt, wie Smart Speech Flow mit echten Nutzerinnen und Nutzern getestet werden soll, um den Weg vom MVP zur Produktvision belastbar zu steuern.

Ziel ist nicht nur Usability-Feedback im engen Sinn. Das Usertesting soll helfen zu beantworten:

- ob das Produkt in realen Gespraechssituationen wirklich funktioniert
- welche Anforderungen im Alltag tatsaechlich zaehlen
- welche Modelle, Konfigurationen und Interaktionsmuster den groessten Mehrwert bringen
- welche Ideen weiterverfolgt und welche bewusst verworfen werden sollten

Im Fokus des Usertestings stehen die beiden eigentlichen Produktrollen:

- Admin
- Customer

Nicht im Vordergrund stehen dagegen technische Entwicklerperspektiven oder Integrationsaufgaben. Das Testing soll in erster Linie zeigen, ob Smart Speech Flow fuer die Menschen funktioniert, die das Produkt im Gespraech tatsaechlich nutzen.

## Zielbild

Am Ende des Usertestings soll belastbar beantwortet werden koennen:

- ob Customer unmittelbar verstehen, was zu tun ist
- ob Customer sich gefuehrt und informiert fuehlen
- ob Admins Sessions sicher starten, begleiten und bei Problemen stabil handhaben koennen
- ob Realtime-Status, Wartezeiten und Fehlerzustaende verstaendlich und handhabbar sind
- ob das System auch unter unguenstigen Bedingungen noch als verlaesslich wahrgenommen wird

## Angestrebte Erfolgskriterien

Die folgenden Werte sollen als pragmatische Arbeitsziele fuer die Bewertung der Produktreife dienen:

- hohe Erfolgsquoten in den Kernflows fuer Admin und Customer
- gutes Verstaendnis dafuer, was waehrend Processing und Statuswechseln passiert
- ein belastbarer Wiedereinstieg nach Abbruch oder Verbindungsverlust
- keine offenen kritischen Blocker vor Pilotierungen oder breiteren Tests

Diese Zielwerte sollen Orientierung geben. Sie ersetzen nicht die qualitative Bewertung des eigentlichen Gespraechserlebnisses.

## Produktfragen, die das Testing beantworten soll

Das Usertesting soll vor allem folgende Fragen klaeren:

- Wie gut gelingt ein Gespraech mit SSF unter realen Bedingungen?
- Welche Friktionen treten im Gespraechsfluss auf?
- In welchen Situationen ist Audio sinnvoller als Text und umgekehrt?
- Wann funktionieren zwei Geraete gut und wann ist ein Ein-Geraet-Szenario realistischer?
- Welche Bedienmuster werden intuitiv verstanden und welche nicht?
- Wie gross ist der Unterschied zwischen technischer Qualitaet und wahrgenommener Gespraechsqualitaet?
- Welche Modelle und Settings liefern in welchem Kontext den besten Kompromiss aus Qualitaet, Geschwindigkeit und Stabilitaet?
- Wo hilft zusaetzlicher Kontext, etwa durch Glossare oder Wissensquellen, wirklich weiter?

## Leitprinzipien

- So frueh wie moeglich mit echten Nutzerinnen und Nutzern testen
- Nicht nur Funktionen testen, sondern Gespraeche beobachten
- Nicht nur Fehler sammeln, sondern Entscheidungen vorbereiten
- Nicht jede Idee sofort bauen, sondern erst validieren
- Qualitative Beobachtung und quantitative Daten kombinieren
- Unterschiedliche Einsatzkontexte bewusst getrennt auswerten

## Wer getestet werden sollte

Smart Speech Flow sollte nicht nur mit internen oder techniknahen Personen getestet werden. Sinnvoll sind mehrere Nutzergruppen:

- Admins, also Mitarbeitende, die eine Session starten, steuern oder moderieren
- Customer, also Endnutzerinnen und Endnutzer, die moeglichst niedrigschwellig durch den Gespraechsprozess gefuehrt werden sollen
- Moderierende oder beobachtende Fachkraefte in begleiteten Tests

Wichtig ist, dass nicht nur geuebte Testpersonen teilnehmen. Das Produkt muss gerade mit Menschen funktionieren, die SSF zum ersten Mal sehen.

Fuer Customer-Tests ist besonders wertvoll:

- eine Mischung aus geringer und mittlerer Technikaffinitaet
- unterschiedliche reale Nutzungskontexte, zum Beispiel Smartphone und Notebook
- moeglichst realistische sprachliche und situative Voraussetzungen

Fuer Admin-Tests ist besonders wertvoll:

- Erfahrung mit moderierten oder betreuten Prozessen
- Grundverstaendnis fuer Session- oder Einladungssituationen
- ein realistischer Bezug zu Situationen mit Uebersetzungsbedarf

## Welche Szenarien getestet werden sollten

Das Testing sollte nicht auf einen einzigen Idealablauf beschraenkt bleiben. Es braucht ein Set klarer Nutzungsszenarien.

### Basisszenarien

- Zwei Gespraechspartner, zwei Endgeraete
- Admin und Customer mit Session-Link und Standard-Flow
- Audio- und Textnutzung im Wechsel

### Erweiterte Gespraechsszenarien

- Zwei Gespraechspartner mit nur einem Device
- Kurzgespraeche mit hoher Taktung
- laengere Beratungsgespraeche mit mehreren Rueckfragen
- schlechte Netzsituation oder Unterbrechung
- Wiederbeitritt nach Verbindungsverlust

### Interaktionsszenarien

- Push-to-talk
- Auto-Aufnahme
- textzentrierte Nutzung
- audiozentrierte Nutzung
- einfache mobile Nutzung
- app-nahe oder kioskartige Nutzung
- Wiederholen, Playback und Download von Ergebnissen

### Kontext- und Wissensszenarien

- Gespraeche ohne Zusatzkontext
- Gespraeche mit Glossar oder domanenspezifischen Begriffen
- Gespraeche mit angebundener Wissensdatenbank oder vordefinierten Inhalten

## Was genau getestet werden sollte

Die Aufgaben und Beobachtungen sollten rollengetrennt geplant werden. Dadurch wird klarer, welche Probleme dem Admin-Flow und welche dem Customer-Erlebnis zuzuordnen sind.

### 1. Gespraechsfluss

- Wie schnell kommt das Gespraech in Gang?
- Wie oft stockt der Austausch?
- Wie oft muessen Aussagen wiederholt werden?
- Wie klar ist, wer gerade spricht oder sprechen soll?

### 2. Bedienbarkeit

- Ist die Rollenlogik verstaendlich?
- Ist die UI ohne Einweisung bedienbar?
- Werden Status, Unsicherheiten und Verbindungszustaende verstanden?
- Ist der Audio-Flow nachvollziehbar?
- Verstehen Customer, was sie als Naechstes tun sollen?
- Koennen Admins den Prozess erklaeren, steuern und bei Problemen loten?

### 3. Qualitaet der Ergebnisse

- Verstehen beide Seiten den Inhalt korrekt?
- Wie haeufig sind Transkriptions- oder Uebersetzungsfehler wirklich geschaeftskritisch?
- Wie wird die Qualitaet subjektiv wahrgenommen?
- Welche Unterschiede zeigen Modelle, Sprachpaare und Konfigurationen?
- Wie natuerlich und hilfreich wird die TTS-Ausgabe wahrgenommen?
- Wuerden sich die Beteiligten in einer echten Situation auf das Ergebnis verlassen?

### 4. Interaktionsmuster

- Wann hilft Auto-Aufnahme und wann stoert sie?
- Wann ist ein Ein-Geraet-Flow sinnvoller als ein Zwei-Geraete-Flow?
- Welche UI-Variante funktioniert in welchem Kontext besser?
- Welche Rolle spielen Progress, Realtime-Feedback und Recovery-Hinweise fuer das Vertrauen?

### 5. Kontextanreicherung

- Verbessern Glossare oder Wissensquellen das Ergebnis wirklich?
- Erhoehen sie Vertrauen und Verstaendlichkeit?
- Fuehren sie zu relevanteren und konsistenteren Uebersetzungen?

## Testarten

Das Usertesting sollte mehrere Formate kombinieren:

### Explorative Produkttests

Offene Tests mit Beobachtung, um Friktionen, Missverstaendnisse und unerwartete Nutzungsmuster zu erkennen.

### Aufgabenbasierte Tests

Die Teilnehmenden bearbeiten konkrete Gespraechsaufgaben mit vorgegebenem Ziel. So wird vergleichbar, ob ein Flow wirklich funktioniert.

Empfehlenswert ist, Admin- und Customer-Aufgaben zunaechst getrennt zu testen. Spaeter sollten ergaenzend gepaarte Sessions folgen, um den realen Gespraechsmodus gezielt zu beobachten.

### Moderierte Remote-Tests

Moderierte Think-aloud-Tests sind fuer SSF besonders geeignet, weil sie Missverstaendnisse, Wartefrust, Unsicherheiten und Vertrauen in Echtzeit sichtbar machen.

### Unmoderierte Kurztests

Ergaenzende kurze Tests koennen hilfreich sein, um Verstaendlichkeit, Vertrauen, Wartezeitwahrnehmung und einzelne UI-Elemente mit groesserer Stichprobe schneller zu ueberpruefen.

### Pilotierungen im realen Umfeld

Begrenzte Einsaetze in echten Organisationen, um zu verstehen, wie SSF im Alltag genutzt wird und welche Anforderungen sich erst dort zeigen.

### Modell- und Konfigurationsvergleiche

Vergleichstests mit unterschiedlichen ASR-, Uebersetzungs- und TTS-Modellen sowie verschiedenen Settings fuer Latenz, Qualitaet und Stabilitaet.

### UI- und Interaktionsvergleiche

Tests verschiedener Bedienkonzepte, zum Beispiel klassische Web-UI, mobile Optimierung, Ein-Geraet-Szenario oder Auto-Aufnahme.

## Messkriterien

Das Testing sollte nicht nur auf Bauchgefuehl beruhen. Sinnvolle Kriterien sind:

- Erfolgsgrad einzelner Aufgaben, zum Beispiel Success, Partial oder Fail
- grobe Bearbeitungszeit pro kritischem Task
- Anzahl noetiger Hinweise oder Eingriffe
- Zeit bis zum erfolgreichen Gespraechsstart
- Anzahl noetiger Wiederholungen pro Gespraech
- Anzahl technischer Abbrueche oder Wiederverbindungen
- wahrgenommene Verstaendlichkeit
- wahrgenommenes Vertrauen in die Ergebnisse
- subjektive Bedienbarkeit
- Anteil erfolgreich abgeschlossener Aufgaben
- Unterschied zwischen gemessener und wahrgenommener Qualitaet

Fuer SSF besonders wichtig sind ausserdem:

- Verstaendnis der Frage, was waehrend Processing oder Wartezeiten gerade passiert
- subjektives Sicherheitsgefuehl trotz kleiner Fehler oder Unsicherheiten
- Trennschaerfe zwischen Admin- und Customer-Sicht, sofern bestimmte Informationen nur fuer eine Rolle sichtbar sein sollen

## Was nach jedem Test erfasst werden sollte

- Kontext des Tests
- beteiligte Nutzergruppe
- Sprachpaar und Gespraechsart
- genutztes Device-Setup
- verwendete Modelle und Konfigurationen
- beobachtete Friktionen
- Verbesserungsvorschlaege der Nutzenden
- offene Produktfragen
- klare Entscheidungsempfehlung

Wenn moeglich, sollte pro Finding auch festgehalten werden:

- welche Rolle betroffen war
- in welchem Task oder Szenario das Problem auftrat
- wie haeufig oder wie schwerwiegend das Problem war

## Entscheidungen, die aus dem Testing abgeleitet werden sollen

Das Usertesting ist nur dann wertvoll, wenn Ergebnisse in Produktentscheidungen uebersetzt werden.

Nach jedem Testzyklus sollte deshalb entschieden werden:

- Was wird sofort verbessert?
- Was wird weiter getestet?
- Was wird bewusst vorerst nicht verfolgt?
- Welche Idee wird in die Roadmap aufgenommen?
- Welche Hypothese hat sich nicht bestaetigt?

Dabei soll nicht nur entschieden werden, was gebaut wird, sondern auch, was bewusst nicht weiterverfolgt wird.

## Taktung

Empfehlenswert ist ein wiederkehrender Rhythmus:

- kleine, schnelle Tests in kurzen Abstaenden
- groessere Testzyklen vor wichtigen Produktentscheidungen
- Pilotierungen in realen Umfeldern vor breiterer Oeffnung
- erneute Tests nach groesseren Aenderungen an Flow, UI, Modellen oder Konfigurationen

Ein sinnvoller Rhythmus ist:

- kleinere, haeufige Testrunden in kurzen Abstaenden
- vollere Testrunden vor Piloten, Releases oder groesseren Richtungsentscheidungen
- gezielte Re-Tests auf bereits identifizierte Top-Probleme

## Auswertung und Priorisierung

Die Beobachtungen aus dem Usertesting sollten in eine klare Priorisierungslogik uebersetzt werden.

Sinnvoll ist eine Einteilung nach Schweregrad, zum Beispiel:

- kritische Blocker
- schwere Probleme mit hoher Auswirkung auf Verstaendlichkeit, Vertrauen oder Recovery
- mittlere Probleme mit Umwegen oder Frustration
- kleinere kosmetische Probleme

Wichtig ist, dass Findings nicht nur dokumentiert, sondern mit einer klaren Bewertung fuer Produktwirkung, Haeufigkeit und Umsetzungsaufwand versehen werden.

## Organisatorische Voraussetzungen

Damit das Usertesting tragfaehig wird, braucht es:

- klar definierte Testziele pro Zyklus
- vorbereitete Szenarien und Beobachtungsleitfaeden
- Einwilligung und sensible Behandlung personenbezogener Inhalte
- eine saubere Dokumentation der Ergebnisse
- eine eindeutige Rueckkopplung in Produktsteuerung und Roadmap

Hilfreich ist ausserdem:

- eine stabile Testumgebung
- vorbereitete Testdaten und wiederverwendbare Szenarien
- klare Rollen- und Aufgabenbilder fuer Admin und Customer

## Erfolgsbild

Das Usertesting ist erfolgreich, wenn Smart Speech Flow nicht nur technisch besser wird, sondern produktseitig klarer.

Das bedeutet:

- die wichtigsten Gespraechsszenarien sind verstanden
- Produktentscheidungen basieren weniger auf Annahmen und mehr auf beobachtetem Verhalten
- Modelle, Settings und Interaktionsmuster werden nicht nur ausprobiert, sondern gezielt bewertet
- die Roadmap wird durch reales Lernen geschaerft
- SSF entwickelt sich entlang echter Nutzung statt entlang interner Vermutungen
