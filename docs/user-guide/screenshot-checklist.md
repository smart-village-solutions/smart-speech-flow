# Checkliste für Screenshots und Bilder der KasselDIALOG-Nutzerdokumentation

**Ziel:** Bildmaterial für die 26 [Markdown-Folien](pages/) im A4-Querformat. Die [Gestaltungsreferenz](<../guides/Erklärfolien Kassel Dialog 001screen.pdf>) bestimmt nur den Stil, nicht die dargestellten Abläufe oder Aussagen.

## Vor der Aufnahme

- [ ] Die dokumentierte KasselDIALOG-Version und das Aufnahmedatum festhalten. Alle Produktansichten stammen aus derselben freigegebenen Version.
- [ ] Ein Testkonto und ein vollständig erfundenes Gespräch auf zwei Geräten oder Browsern vorbereiten: Mitarbeitendenansicht auf Deutsch, Gästeansicht in einer anderen Sprache.
- [ ] Zwei Testkonfigurationen vorbereiten: optionale Speicherung **aktiviert** und **deaktiviert**. Für die Doku gilt die Vorgabe, dass die Speicherfrage nur im aktivierten Fall erscheint.
- [ ] Browserfenster, Zoom und Bildausschnitt für gut lesbare Screenshots im A4-Querformat festlegen. Sensible Browserleisten, Benachrichtigungen und fremde Anwendungen ausblenden.
- [ ] Nur Testdaten zeigen. Keine echten Namen, E-Mail-Adressen, Gesprächsinhalte, Zugangsdaten oder noch nutzbaren Sitzungscodes und Einladungslinks veröffentlichen. QR-Code und Link derselben Einladung müssen zusammenpassen und vor Veröffentlichung ungültig sein.
- [ ] Freigegebene Datenschutzinformation und ihren konkreten Zugangsweg abwarten, bevor Folien 08, 21 und 22 endgültig bebildert werden.

## Screenshots aus der Anwendung

Ein Kästchen steht für einen benötigten Bildausschnitt. Derselbe Screenshot kann auf mehreren Folien verwendet und dort anders zugeschnitten werden. Vorhandene Aufnahmen liegen unter `screenshots/`, Grafiken unter `graphics/`. Die Kästchen bleiben bis zur redaktionellen Abnahme offen.

| Erledigt | Kennung | Motiv und sichtbares Detail | Folien |
| --- | --- | --- | --- |
| [ ] | P00 | Einladungsemail „Willkommen bei KasselDIALOG!“ mit „Passwort festlegen“; Empfänger und Einladungs-URL unkenntlich. Aufnahme vorhanden: `screenshots/P00-Email.png`. | [04](pages/04-einladung-und-passwort-festlegen.md) |
| [ ] | P01 | Zwischenseite „Passwort aktualisieren“ mit „Klicken Sie hier um fortzufahren“. Aufnahme vorhanden: `screenshots/P01-Passwort-ändern.png`. | 04 |
| [ ] | P02 | Formular „Passwort aktualisieren“ mit leeren Feldern und „Absenden“. Aufnahme vorhanden: `screenshots/P02-Neues-Passwort.png`. | 04 |
| [ ] | P03 | Anmeldeseite „Bei Ihrem Konto anmelden“ mit leeren Feldern und „Anmelden“. Aufnahme vorhanden: `screenshots/P03-Login.png`. | [05](pages/05-anmelden.md) |
| [ ] | S01 | Startseite mit „Login“; keine echte Sitzung im Eingabefeld. Der Screenshot-Wortlaut weicht vom Repository-Textkatalog „Admin-Login“ ab. | 05 |
| [ ] | S02 | Auswahl der Abteilung oder Organisation nach „Login“; Testorganisation oder freigegebener Name. | 05 |
| [ ] | S03 | Gesprächsübersicht mit „Neues Gespräch starten“. Die vorhandene Aufnahme zeigt eine leere Liste; für die Wiederaufnahme einer eigenen Sitzung wäre ein zusätzlicher Zustand nötig. | [06](pages/06-gespraech-eroeffnen.md) |
| [ ] | S04 | Warnung „Laufendes Gespräch beenden?“ mit „Trotzdem starten“ und „Abbrechen“. Aufnahme vorhanden: `screenshots/S04-Warnung.png` (redaktionelle Abnahme ausstehend). | 06 |
| [ ] | S05 | Einladung mit Sitzungscode, „Link kopieren“, sichtbarem Link, QR-Code, „Zum Gespräch wechseln“ und „Abbrechen“. Code, Link und QR-Code gehören zur selben später beendeten Testsitzung. | [07](pages/07-einladung-anzeigen.md), [08](pages/08-einladung-weitergeben-und-warten.md) |
| [ ] | S06 | Gästeansicht für die Sprachauswahl nach Beitritt per Code, Link oder QR-Code. | 08 |
| [ ] | S07 | Gäste-Infoseite bei **aktivierter** optionaler Speicherung: freiwillige Speicherfrage und „Loslegen“. Freigegebenen Wortlaut prüfen. | 08, [21](pages/21-datenschutz-im-gespraech.md) |
| [ ] | S08 | Gäste-Infoseite bei **deaktivierter** Speicherung: keine Speicherfrage; „Loslegen“ bleibt möglich. Aufnahme vorhanden: `screenshots/S08-Infoseite-ohne-Frage.png` (englische Gästeansicht; redaktionelle Abnahme ausstehend). | 08, 21 |
| [ ] | S09 | Laufendes Gespräch in der Mitarbeitendenansicht mit Sitzungscode, Verbindungsstatus, gewählter Gastsprache, Nachrichten und Eingabe. | [01](pages/01-titel.md) als mögliches Titelmotiv, [09](pages/09-gespraechsansicht-verstehen.md) |
| [ ] | S10 | Eingabe vor und während einer gesprochenen Nachricht: Mikrofonsymbol „Aufnehmen“, Aufnahmezustand und Sendesymbol „Aufnahme senden“. Die 20-Sekunden-Grenze steht im Text; sie muss nicht im Bild demonstriert werden. | [10](pages/10-nachricht-sprechen.md), [11](pages/11-spracheingabe-senden-und-uebersetzung-lesen.md) |
| [ ] | S11 | Nach dem Senden: erkannter eigener Text in der Mitarbeitendenansicht, mit derselben erfundenen Nachricht wie S10. | 11 |
| [ ] | S12 | Geöffnete Texteingabe mit erfundenem Entwurf und Sendesymbol „Text senden“. | [12](pages/12-nachricht-schreiben.md) |
| [ ] | S13a | Mitarbeitendenansicht eines erfundenen Austauschs: eigene Nachricht im Original und eingehende Nachricht übersetzt. | [13](pages/13-uebersetztes-gespraech-sehen.md) |
| [ ] | S13b | Gästeansicht **desselben** Austauschs: zu S13a passende Original- und Übersetzungsnachrichten. | 13 |
| [ ] | S14 | Eingehende Nachricht mit Sprachausgabe und sichtbarer Wiedergabesteuerung „Abspielen“; gegebenenfalls zusätzlich „Pausieren“. | [14](pages/14-uebersetzte-nachricht-anhoeren.md) |
| [ ] | S15 | „Gespräch beenden“ und der Bestätigungsdialog mit „Beenden“ und „Abbrechen“. | [16](pages/16-gespraech-beenden.md) |
| [ ] | S16 | Feedbackformular: drei Sternebewertungen, Weiterempfehlung, freiwilliges Textfeld und „Feedback senden“. Falls nicht gleichzeitig lesbar, zwei aufeinander abgestimmte Ausschnitte aufnehmen. | [25](pages/25-feedback-geben.md) |

Die vier P00–P03-Aufnahmen dokumentieren den nun bestätigten Erstzugang. Vor Freigabe der Bilder Absender, Linkfrist und Wortlaut mit einer aktuellen Einladung vergleichen; die Häkchen bleiben bis zur redaktionellen Abnahme offen.

**Optionaler Bedienhinweis:** Ein Browserdialog zur Mikrofonfreigabe kann [Folie 10](pages/10-nachricht-sprechen.md) ergänzen. Er ist browserabhängig und darf nicht als einheitliche KasselDIALOG-Ansicht erscheinen.

## Grafiken und andere Bildbausteine

| Erledigt | Kennung | Bildbaustein | Folien |
| --- | --- | --- | --- |
| [ ] | G01 | Titelkomposition aus freigegebener Gesprächsansicht oder schlichtem Produktmotiv; keine zusätzliche Produktaussage. | 01 |
| [ ] | G02 | Übersicht „Mitarbeitende ↔ KasselDIALOG ↔ Gast“ mit Übersetzungsrichtung. Vektorgrafik vorhanden: [`graphics/G02.svg`](graphics/G02.svg). | [02](pages/02-kasseldialog-auf-einen-blick.md) |
| [ ] | G03 | Vier Symbole für Einsatzfreigabe, Gerät/Verbindung, Datenschutzinformation und menschlichen Prüfweg. Vektorgrafik vorhanden: [`graphics/G03.svg`](graphics/G03.svg). | [03](pages/03-vor-dem-gespraech.md) |
| [ ] | G04 | Ablauf „Sprache → erkannter Text → Übersetzung → Nachricht/Sprachausgabe“. Vektorgrafik vorhanden: [`graphics/G04.svg`](graphics/G04.svg); Aussage zum lokalen Modellbetrieb vor Freigabe prüfen. | [17](pages/17-so-unterstuetzt-ki-das-gespraech.md) |

Die Folien [15](pages/15-unklarheiten-klaeren.md), [18](pages/18-ki-grenzen-erkennen.md), [19](pages/19-praxisfall-uebersetzungsfehler.md), [20](pages/20-bei-uebersetzungsfehlern-handeln.md), [22](pages/22-datenverarbeitung-und-rechte.md), [23](pages/23-probleme-loesen.md), [24](pages/24-haeufige-fragen.md) und [26](pages/26-hilfe-und-dokumentstand.md) benötigen keinen eigenen Screenshot. Ihre Regeln, Schritte oder Tabellen sollen groß und gut lesbar bleiben.

## Bildredaktion und Abnahme

- [ ] Ausschnitte auf die jeweilige Handlung begrenzen; Schaltflächen und Schrift müssen in Word **und** PDF lesbar sein. Pro Screenshot höchstens drei nummerierte Markierungen verwenden und diese im Folientext erklären.
- [ ] Für S10–S14 dieselbe Testsitzung und konsistente Beispielsätze verwenden. Mitarbeitenden- und Gästeansicht in S13a/S13b müssen dieselben Nachrichten aus jeweils ihrer Sicht zeigen.
- [ ] Bilder mit beschreibendem Alternativtext in die Markdown-Folien einbinden. Für rein dekorative Elemente einen leeren Alternativtext verwenden.
- [ ] Screenshots nach dem Beenden der Testsitzung noch einmal auf nutzbare Links, Codes, QR-Ziele und personenbezogene Daten prüfen.
- [ ] Beide Speicher-Konfigurationen sichtbar gegen die ausgelieferte Version prüfen; die Checkliste und Folien setzen voraus, dass die Speicherfrage im deaktivierten Fall fehlt.
- [ ] Datenschutzbilder und Feedbackformular erst nach fachlicher Freigabe ihres Wortlauts verwenden. Anschließend jede fertige Folie im exportierten Word und PDF auf Beschnitt, Kontrast und Lesbarkeit prüfen.
