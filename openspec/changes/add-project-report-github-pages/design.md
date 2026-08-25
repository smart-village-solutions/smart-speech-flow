## Context

Smart Speech Flow ist ein Python-/Docker-Microservice-System. Das bestehende
Produktfrontend unter `services/frontend` ist die öffentliche
Gesprächsanwendung. Der Projektbericht ist dagegen ein internes
Entwicklungsartefakt und soll keine Laufzeitabhängigkeit auf die Produktdienste
erzeugen.

## Goals / Non-Goals

- Goals:
  - Einen statischen, versionierten Statusbericht als GitHub Page veröffentlichen.
  - Den JSON-Vertrag beim Start der Anwendung strikt validieren.
  - Meilenstein- und Arbeitspaketansichten mit teilbaren URL-Filtern bereitstellen.
- Non-Goals:
  - Keine Bearbeitung der Daten in der ausgelieferten Anwendung.
  - Keine Anbindung an Jira, GitHub, Redis oder SSF-APIs.
  - Keine Änderung am Gesprächsfrontend oder den Microservices.

## Decisions

- Decision: Der Bericht wird als eigenständige Vite/React-App unter
  `apps/project-report` aufgebaut.
  - Rationale: Das Produktfrontend bleibt von internem Planungs-UI und dessen
    Abhängigkeiten getrennt.
- Decision: `project-status.json` wird in den App-Quelltext eingecheckt und
  beim Build ausgeliefert.
  - Rationale: Jede Anzeige ist eindeutig einem Repository-Commit zugeordnet.
- Decision: Die Produktion ist read-only; die JSON-Datei wird ausschließlich
  über Änderungen im Repository gepflegt.
  - Rationale: GitHub Pages kann keine sichere serverseitige Schreiblogik
    bereitstellen.
- Decision: Deployment erfolgt mit GitHub Actions und den offiziellen
  Pages-Actions.
  - Rationale: Keine zusätzliche Infrastruktur oder Laufzeitcontainer nötig.

## Risks / Trade-offs

- GitHub Pages veröffentlicht den kompletten statischen Datensatz an alle
  Seitenbesucher. → Nur nicht vertrauliche Planungsdaten einchecken.
- Der Status aktualisiert sich nicht automatisch. → `meta.updatedAt` und
  `meta.source` machen Datenstand und Herkunft sichtbar.
- Eine weitere Node-Anwendung erhöht Build-Wartung. → Eigenes, kleines
  `package.json` und unabhängige Build-Pipeline verwenden.

## Migration Plan

1. Die aktuelle Planungsdatei in den Datenordner der App übernehmen und gegen
   den Berichtvertrag validieren.
2. App und Workflow hinzufügen.
3. GitHub Pages in den Repository-Einstellungen auf „GitHub Actions“ als Quelle
   setzen.
4. Nach erfolgreichem Build die Page-URL prüfen.

Rollback: Den Pages-Workflow deaktivieren oder zurücknehmen; die SSF-Laufzeit
bleibt davon unberührt.

## Open Questions

- Welche Sichtbarkeit und Ziel-URL ist für die GitHub Page vorgesehen?
