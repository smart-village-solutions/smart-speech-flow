# Change: Add multi-tenant operations

## Why

Ab Oktober 2026 sollen mehrere Organisationen Smart Speech Flow auf derselben
Instanz regulär nutzen. Dafür müssen Tenant-Kontext, Datenisolation,
Provisionierung und betriebliche Verantwortlichkeiten vor dem Regelbetrieb
verbindlich umgesetzt und erprobt sein.

## What Changes

- Ein verbindliches Mandantenmodell einschließlich Tenant-Lebenszyklus,
  Rollen- und Betreibergrenzen definieren.
- Tenant-Kontext in den Anfrage-, Session-, Nachrichten-, Audio- und
  Konfigurationspfaden durchsetzen.
- Tenantübergreifenden Zugriff mit automatisierten Negativtests verhindern.
- Einen Mehrorganisations-Pilot einschließlich Provisionierung und
  Supportabläufen durchführen.

## Impact

- Affected specs: `multi-tenant-operations` (neu)
- Affected code: API-Gateway, Session- und Datenspeicherpfade,
  Authentifizierung/Berechtigung, Monitoring und Tests
- **BREAKING:** Bestehende interne Aufrufe können einen expliziten
  Tenant-Kontext benötigen.
