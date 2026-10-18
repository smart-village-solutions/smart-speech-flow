# Redaktionsleitfaden für die KasselDIALOG-Nutzerdokumentation

**Status:** Entwurf
**Sprache der Nutzerdokumentation:** Deutsch
**Zielgruppe:** Mitarbeitende, die mit KasselDIALOG Gespräche führen.

Dieser Leitfaden legt fest, wie die einzelnen Markdown-Folien der [Gliederung](ssf-operator-user-guide-outline.md) aufgebaut werden. Der [Folienplan](ssf-operator-user-guide-slide-plan.md) legt ihre Reihenfolge und jeweilige Aussage fest. Der Leitfaden sorgt für einheitliche Inhalte und erleichtert die spätere Erstellung einer Word-Datei und eines PDF. Die Regeln gelten für die Nutzerdokumentation der gesprächsführenden Mitarbeitenden; eigenständige Anleitungen für Gäste und Administrierende sind nicht Teil davon.

## Gestaltungsziel und Referenz

Der [KasselDIALOG-Gestaltungsentwurf](<Erklärfolien Kassel Dialog 001screen.pdf>) hat neun Seiten im A4-Querformat (297 × 210 mm). Er verwendet eine weiße Titelfolie und überwiegend blaue Inhaltsfolien mit großen Bildern, gut lesbarer heller Schrift und wenig Text. Dieses **folienartige Querformat** ist das Ziel der KasselDIALOG-Nutzerdokumentation. Es ist für die Betrachtung am Bildschirm ausgelegt und bleibt im A4-Format druckbar.

Der Entwurf ist ausschließlich eine Referenz für Seitenformat, Farb- und Bildwirkung sowie die Verteilung von Text und Bild. Seine Texte, beschriebenen Abläufe, Bedienoberflächen und Sachbehauptungen werden nicht als Grundlage für die KasselDIALOG-Nutzerdokumentation verwendet. Die Inhalte werden unabhängig davon anhand der heutigen KasselDIALOG-Installation und der fachlich geprüften Projektunterlagen erarbeitet.

## Dateien und Reihenfolge

Die geplanten Folien liegen unter `docs/user-guide/pages/`, die verwendeten Bilder unter `docs/user-guide/images/`. Die Dateinamen beginnen mit einer zweistelligen Nummer und einem kurzen deutschen Thema, zum Beispiel `06-gespraech-eroeffnen.md`. Diese Nummern legen die Reihenfolge beim Zusammenführen fest. Bilder werden relativ zur Foliendatei eingebunden, zum Beispiel `../images/gespraechsansicht.png`.

Eine Markdown-Datei beschreibt eine geplante Folie. Titelblatt und Abschlussfolie dürfen von den folgenden Vorlagen abweichen. Ob eine Datei nach dem Export tatsächlich genau eine Querformatseite füllt, wird an der gesetzten Word-Datei und am PDF geprüft.

Die 26 Folien-Dateien enthalten Textentwürfe. Geplante Bilder sind bis zur Erstellung der Screenshots in HTML-Kommentaren beschrieben. Nach der Bildredaktion werden sie mit beschreibendem Alternativtext eingebunden.

## Gemeinsame Regeln für jede Seite

1. Die Seite beginnt mit genau einer Hauptüberschrift (`#`). Der Titel benennt die Aufgabe oder das Thema.
2. Ein kurzer Einstieg erklärt, was die lesende Person auf dieser Folie erfährt oder erledigt. Jede Folie hat eine Hauptaussage; längere Abläufe werden auf mehrere Folien verteilt.
3. Handlungen werden als nummerierte Schritte formuliert. Hinweise und Voraussetzungen stehen unmittelbar bei der betroffenen Handlung.
4. Bezeichnungen von Schaltflächen und Menüs entsprechen der heutigen KasselDIALOG-Oberfläche. Sie werden in Anführungszeichen gesetzt, zum Beispiel „Neues Gespräch starten“.
5. Jedes Bild erhält einen beschreibenden Alternativtext und bei Bedarf eine kurze Bildunterschrift. Bilder und Screenshots erhalten genügend Fläche, damit Details im Querformat lesbar bleiben. Screenshots verwenden Testdaten und zeigen nur die für den Schritt nötigen Bereiche.
6. Die Seite enthält nur Funktionen, die in der dokumentierten Version freigegeben sind. Aussagen zu Datenverarbeitung, Aufbewahrung und lokalen Modellen werden für die konkrete Installation geprüft.
7. Layoutangaben wie Ränder, Schriftgrößen, Hintergrund, Logo und Folienwechsel stehen nicht im Fließtext. Sie werden durch die Gestaltungsvorlage und die Dokumentenerzeugung gesteuert.

Die Folien zur KI-Nutzung erklären nur die für KasselDIALOG nötigen Zusammenhänge. Sie benennen typische Fehler, zeigen die Verantwortung der gesprächsführenden Person und enthalten einen kurzen Praxisfall mit Auflösung. Damit unterstützen sie die Entwicklung der für den Einsatz nötigen KI-Kompetenz; eine allgemeine KI-Schulung oder die Einweisung für einen besonderen Einsatzfall ersetzen sie nicht. Die konkreten Lernziele stehen im [Folienplan](ssf-operator-user-guide-slide-plan.md).

## Vorlage 1: Übersicht

Für „KasselDIALOG auf einen Blick“, den Umgang mit KI und Datenschutz. FAQ und Fehlerhilfe nutzen dieselbe Grundstruktur mit Fragen beziehungsweise Problemen als Zwischenüberschriften.

````markdown
# KasselDIALOG auf einen Blick

KasselDIALOG unterstützt ein Gespräch zwischen zwei Menschen in unterschiedlichen Sprachen.

![Zwei Gesprächsansichten während eines übersetzten Austauschs](../images/kasseldialog-uebersicht.png)

*Abbildung: Beide Gesprächsseiten während einer Sitzung.*

## Das Wichtigste

- ...
- ...
- ...
````

Eine Grafik ist sinnvoll, wenn sie einen Ablauf oder Zusammenhang erklärt. Eine reine Textseite, etwa mit häufigen Fragen, braucht keine dekorative Abbildung.

## Vorlage 2: Funktion

Für eine Ansicht oder eine einzelne Bedienfunktion, etwa die Einladung oder die Gesprächsansicht.

````markdown
# Gespräch führen

Auf dieser Seite erfahren Sie, wie Sie eine Nachricht sprechen oder schreiben.

![Gesprächsansicht mit markierten Bedienelementen](../images/gespraechsansicht.png)

*Abbildung: Mikrofon, Texteingabe und Nachrichtenbereich.*

## So gehen Sie vor

1. ...
2. ...
3. ...

## Wenn etwas unklar ist

...
````

Der letzte Abschnitt ist optional. Nummerierte Markierungen im Screenshot und die Erläuterungen im Text müssen dieselben Nummern verwenden.

## Vorlage 3: Schrittfolge

Für einen Ablauf mit mehreren Ansichten, etwa Anmeldung, Einladung oder Gesprächsabschluss.

````markdown
# Gast einladen

Nach dem Start einer Sitzung können Sie dem Gast einen Zugang weitergeben.

## 1. Einladung anzeigen

![Ansicht mit Sitzungscode und QR-Code](../images/einladung-anzeigen.png)

*Abbildung: Die Einladung zur geöffneten Sitzung.*

...

## 2. Zugang weitergeben

...

## Ergebnis

Der Gast kann der Sitzung beitreten.
````

Eine Schrittfolge enthält normalerweise zwei bis drei Schritte. Wenn ein Ablauf auf einer Querformatfolie zu eng wird, wird er auf zwei geplante Folien verteilt; Bilder werden nicht bis zur Unlesbarkeit verkleinert.

## Erstellung von Word und PDF

Die Markdown-Dateien werden in der festgelegten Reihenfolge zu einem Dokument zusammengeführt. Die bearbeitbare Word-Datei und das PDF sollen beide A4-Querformat (297 × 210 mm) verwenden und dieselbe Foliengestaltung zeigen. Die Gestaltungsvorlage regelt insbesondere Hintergrund, Logo, Überschriften, Text, Bilder und Ränder. Der konkrete Exportweg wird zunächst mit einer Musterfolie geprüft; erst dann wird die vollständige Dokumentenerzeugung eingerichtet.

Vor der Freigabe werden beide Ausgaben visuell geprüft: Entspricht jede Markdown-Datei genau einer Folie? Sind Bilder und Markierungen aus normalem Betrachtungsabstand lesbar? Sind Kontrast und Textmenge angemessen? Gibt es leere oder überlaufende Folien? Die Inhalte werden ausschließlich gegen die heutige KasselDIALOG-Installation und ihre freigegebenen Quellen geprüft.
