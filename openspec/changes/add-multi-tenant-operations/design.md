## Context

Der bisherige MVP-Fokus liegt auf einem stabilen Gesprächsprodukt. Der geplante
Regelbetrieb ab Oktober umfasst jedoch mehrere Organisationen. Mandantenfähigkeit
ist deshalb keine optionale Verwaltungsfunktion mehr, sondern eine Sicherheits-
und Betriebsanforderung.

## Goals / Non-Goals

- Goals:
  - Strikte tenantübergreifende Isolation für alle produktrelevanten Datenpfade.
  - Nachvollziehbare Provisionierung und Betriebsverantwortung für mehrere Organisationen.
  - Mehrorganisations-Pilot vor der öffentlichen Optimierungsrunde.
- Non-Goals:
  - Keine Abrechnungs- oder Self-Service-Funktionen im ersten Ausbauschritt.
  - Keine Aufweichung der bestehenden Audio-Retention- und Datenschutzregeln.

## Decisions

- Decision: Tenant-Kontext wird serverseitig aus einer vertrauenswürdigen
  Identität oder einer kontrollierten Provisionierung abgeleitet und niemals nur
  aus frei wählbaren Client-Eingaben übernommen.
- Decision: Sessions, Nachrichten, Audiodaten, Konfigurationen, Logs und
  Metriken erhalten tenant-sichere Zugriffspfade.
- Decision: Die rechtliche Prüfung vom 13. bis voraussichtlich 27. August ist
  ein verbindlicher Eingang für das Daten- und Retentionsmodell.

## Risks / Trade-offs

- Nachträgliche Einbettung des Tenant-Kontexts berührt zentrale Pfade. →
  Zuerst Modell und Grenztests definieren, dann schrittweise migrieren.
- Fehlende Tenant-Isolation ist ein Datenschutz- und Sicherheitsrisiko. →
  Fail-closed bei fehlendem oder widersprüchlichem Tenant-Kontext.
- Der Terminplan ist eng. → Auf minimale Isolation und Pilotfähigkeit begrenzen;
  Administration und Abrechnung folgen später.

## Migration Plan

1. Mandantenmodell und rechtliche Vorgaben bis 27.08. freigeben.
2. Isolation und Tenant-Kontext bis 03.09. implementieren und testen.
3. Bis 10.09. mindestens zwei Organisationen provisionieren und pilotieren.
4. Öffentliche Optimierungsrunde und Regelbetrieb nur mit bestandenem
   Isolationsnachweis freigeben.

## Open Questions

- Welcher Identity Provider liefert den vertrauenswürdigen Tenant-Kontext?
- Welche bestehenden Daten müssen vor dem Mehrorganisations-Pilot migriert werden?
