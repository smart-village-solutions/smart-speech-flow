## ADDED Requirements

### Requirement: Versionierter statischer Projektstatus

Die Anwendung SHALL einen versionierten Projektstatus ausschließlich aus einer
im Repository eingecheckten JSON-Datei laden. Der Datensatz MUST beim Start
gegen das festgelegte öffentliche Status-, Health- und Prioritätsmodell sowie
gegen eindeutige Meilenstein- und Arbeitspaket-IDs validiert werden.

#### Scenario: Gültiger Statusbericht

- **WHEN** die JSON-Datei alle erforderlichen Felder und gültige Referenzen enthält
- **THEN** zeigt die Anwendung den versionierten Projektstatus an

#### Scenario: Ungültiger Statusbericht

- **WHEN** die JSON-Datei unbekannte Statuswerte oder doppelte IDs enthält
- **THEN** bricht die Anwendung mit einem nachvollziehbaren Validierungsfehler ab

### Requirement: Projektstatus visualisieren

Die Anwendung SHALL eine Meilensteinansicht und eine Arbeitspaketansicht
bereitstellen. Der Meilensteinfortschritt MUST nach Aufwand und Statusfortschritt
gewichtet berechnet werden; Arbeitspakete im Status `idea` dürfen nicht in die
Berechnung einfließen.

#### Scenario: Meilensteinfortschritt anzeigen

- **WHEN** ein Meilenstein Arbeitspakete mit Aufwand und Status enthält
- **THEN** zeigt die Anwendung dessen gewichteten Fortschritt, Aufwand und Anzahl der Arbeitspakete an

### Requirement: Teilbare gefilterte Ansichten

Die Anwendung SHALL Meilenstein, Status und Priorität filtern sowie nach ID,
Titel, Bereich und Meilenstein suchen können. Der aktive Ansichts- und
Filterzustand MUST in der URL abgebildet werden.

#### Scenario: Gefilterte Ansicht wiederherstellen

- **WHEN** eine URL mit Ansicht und Filtern geöffnet wird
- **THEN** stellt die Anwendung dieselbe gefilterte Ansicht wieder her

### Requirement: Statische GitHub-Pages-Auslieferung

Die Anwendung SHALL als statisches Artefakt mit GitHub Pages ausgeliefert
werden und MUST keine Laufzeitverbindung zu SSF-Services, Jira oder GitHub
verwenden. Die veröffentlichte Anwendung MUST read-only sein.

#### Scenario: Auslieferung auf GitHub Pages

- **WHEN** Änderungen an der Berichtsanwendung oder ihren Statusdaten auf `main` zusammengeführt werden
- **THEN** baut der GitHub-Actions-Workflow das statische Artefakt und veröffentlicht es als GitHub Page

#### Scenario: Aufruf der veröffentlichten Anwendung

- **WHEN** eine Person die veröffentlichte GitHub Page öffnet
- **THEN** kann sie den Status ansehen und filtern, aber keine Daten verändern
