# Change: Add static project report GitHub Page

## Why

Der Entwicklungsstand von Smart Speech Flow soll als versionierter Projektstatus
für interne Stakeholder transparent und ohne Verbindung zu Laufzeitsystemen
sichtbar sein. Die bestehende Phase-1-Planung liegt bereits als JSON-Snapshot
vor, wird aber noch nicht visualisiert.

## What Changes

- Eine eigenständige React/Vite-Anwendung unter `apps/project-report` ergänzen.
- Die Anwendung als statische GitHub Page ausliefern; sie benötigt kein Backend
  und ruft keine Live-Daten aus GitHub, Jira oder den SSF-Services ab.
- Den Projektstatus aus einer versionierten `project-status.json` validieren und
  in Meilenstein- sowie Arbeitspaketansicht darstellen.
- Filter und Suchbegriff in der URL persistieren und den Fortschritt
  aufwandsgewichtet aus dem öffentlichen Statusmodell berechnen.
- Einen GitHub-Actions-Workflow hinzufügen, der die Anwendung bei Änderungen
  auf `main` baut und als GitHub Page veröffentlicht.

## Impact

- Affected specs: `project-report` (neu)
- Affected code: neue Anwendung unter `apps/project-report`, GitHub-Pages-
  Workflow unter `.github/workflows/`, lokale Statusdaten unter
  `apps/project-report/src/data/`
- Keine Änderung an den SSF-Microservices, deren APIs, Laufzeitdaten oder
  Produktionsfrontend.

## Security Note

GitHub Pages stellt statische Inhalte bereit; alle ausgelieferten Daten sind
für Personen mit Zugriff auf die Seite herunterladbar. Die Statusdatei darf
daher keine vertraulichen Personen-, Sicherheits- oder Betriebsdaten enthalten.
Eine Zugriffsbeschränkung über die SSF-Anwendung selbst ist nicht Teil dieses
Vorhabens.
