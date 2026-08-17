# SVA Studio als Control Plane für SSF

## Zweck und Status

Dieses Dokument beschreibt das Zielbild, nach dem SVA Studio die zentrale
Verwaltungsoberfläche (Control Plane) für Smart Speech Flow (SSF) bereitstellt.
SSF bleibt für Echtzeit-Sessions und die Sprach-KI-Laufzeit verantwortlich;
SVA Studio bündelt die mandantenübergreifende und mandantenlokale Verwaltung.

**Status:** Architektur- und Umsetzungsziel. Die vorhandenen Studio-Fähigkeiten
für Instanzverwaltung, IAM, Organisationen, Audit und Provisionierung bilden
eine Grundlage, decken die SSF-spezifischen Funktionen aber noch nicht ab.

## Architekturgrenze

```text
SVA Studio: Control Plane                 SSF: Runtime
─────────────────────────                 ────────────
Mandanten und Betriebsstatus               Sessions und Einladungen
Identitäten, Rollen und Berechtigungen     Text-, Audio- und Sprachpipeline
Ressourcen, Tarife und Limits              Laufzeitdurchsetzung von Limits
Konfiguration und Freigaben                Session- und Verarbeitungszustand
Audit, Support und Verwaltungs-UI          Laufzeitmetriken und Nutzungsereignisse
          │                                           │
          └──── versionierte API und Ereignisse ─────┘
```

Es gibt keine gemeinsame Datenbank. Studio ist führend für den administrativen
Sollzustand; SSF ist führend für Sessions, Sprachverarbeitung und die daraus
entstehenden Verbrauchs- und Laufzeitdaten.

## Rollenabbildung

Die Begriffe von SSF und die technischen Rollen von Studio dürfen nicht
gleichgesetzt werden. Studio trennt den `platform`-Scope von einem tenantlokalen
`instance`-Scope.

| SSF-Fachrolle | Studio-Scope und Berechtigung | Aufgabe |
| --- | --- | --- |
| SSF-System-Admin | `platform` mit `instance_registry_admin` | Betreiber verwaltet SSF-Mandanten, globale Ressourcen, Support und Betrieb. |
| SSF-Mandanten-Admin | `instance` mit der geschützten Studio-Rolle `system_admin` und SSF-Admin-Permissions | Verwaltet den eigenen Mandanten und seine operativen SSF-Nutzer. |
| SSF-operativer Admin | `instance` mit gezielten `ssf.*`-Permissions | Darf SSF-Sessions erstellen und durchführen, aber keine Mandantenverwaltung vornehmen. |
| SSF-Customer | Keine Studio-Identität erforderlich | Nimmt ausschließlich an einer gültigen SSF-Session teil. |

`instance_registry_admin` bleibt eine Root-only-Plattformrolle. Die
tenantlokale Studio-Rolle `system_admin` darf weder in den Plattform-Scope
eskalieren noch mit der fachlichen SSF-System-Admin-Rolle verwechselt werden.
Neue SSF-Fachzugriffe werden über permissions-basierte Actions (zum Beispiel
`ssf.sessions.create`) modelliert, nicht über weitere feste Rollen.

## Benötigte Studio-Fähigkeiten

### 1. SSF-Mandantenverwaltung

Die vorhandene Instanzverwaltung wird um einen SSF-spezifischen Mandantenbezug
erweitert. Root-Administratoren benötigen eine Mandantenliste und Detailansicht
mit:

- eindeutiger SSF-Tenant-ID und Verknüpfung zur Studio-Instanz,
- Betriebsmodell: Eigenbetrieb, Managed auf Kundeninfrastruktur, Dedicated
  Managed Service, Multi-Tenant oder kommunaler Plattformanbieter,
- Status: angefordert, provisionierend, aktiv, pausiert, stillgelegt,
- Region, Datenresidenz, Vertrag/Tarif und verantwortlichem Betreiber,
- Freigabe- und Provisionierungsstatus sowie nachvollziehbarer Historie.

Studio stößt die Provisionierung über einen idempotenten, asynchronen
Fachvertrag an. SSF bestätigt die technische Bereitstellung, statt dass Studio
direkt Datenbanken, Container oder Laufzeitkonfiguration verändert.

### 2. Identität, Benutzer und Berechtigungen

Studio bleibt die führende Quelle für Benutzer, Organisationen, Gruppen und
administrative Berechtigungen.

- Ein Mandanten-Admin kann operative SSF-Admins einladen, deaktivieren und
  ihren Organisations- oder Teamkontext verwalten.
- Der Permission-Katalog ergänzt SSF-Actions, mindestens für Sessions,
  Sessionverläufe, Konfiguration, Ressourcen, Berichte und Supportfreigaben.
- SSF erhält einen vertrauenswürdigen Tenant- und Berechtigungskontext über
  signierte OIDC-Tokens oder eine serverseitige Token-Introspection; frei
  übermittelte Tenant-IDs sind keine Vertrauensquelle.
- Änderungen an privilegierten Rollen, Supportfreigaben und Löschaufträgen
  nutzen die bestehenden Governance-, Reauth- und Audit-Mechanismen.
- Customers benötigen grundsätzlich kein Studio-Konto. Ein Session-Link oder
  -Code berechtigt ausschließlich zur zugewiesenen SSF-Session und ist zeitlich
  begrenzt.

### 3. SSF-Konfiguration je Mandant

Studio braucht einen SSF-Konfigurationsbereich in der Mandantenansicht:

- erlaubte Sprachen und Sprachpaare,
- aktivierte ASR-, Übersetzungs- und TTS-Provider bzw. freigegebene Modelle,
- Qualitätsprofile `realtime`, `balanced` und `high_quality`,
- Feature-Freigaben, Integrationen, API-Clients und Webhooks,
- Datenverarbeitungs-, Aufbewahrungs- und Löschrichtlinien,
- Branding, Zeitzone, Benachrichtigungs- und Eskalationsregeln.

Studio validiert den gewünschten Sollzustand gegen Tarif, Betriebsmodell,
Sicherheitsvorgaben und verfügbare Runtime-Fähigkeiten. SSF bestätigt jede
angewendete Konfiguration mitsamt Version und Korrelation.

### 4. Ressourcen, Nutzung und Kosten

Für die GPU-Ökonomie benötigt Studio ein Ressourcenmodul mit:

- Limits für Nutzer, gleichzeitige Sessions, Audio-Minuten, Speicher und
  Modell-/Qualitätsprofile,
- Messung nach Mandant, Sprache, Anwendungsfall, Modell, GPU-Sekunden, Latenz,
  Queue-Zeit und Fehlerrate,
- Warnschwellen, Budgets, Übernutzungsschutz und Verbrauchsprognosen,
- tarif- und abrechnungsfähigen, unveränderbaren Nutzungsperioden.

Im Multi-Tenant-Modell verwaltet Studio Quoten gegen einen gemeinsamen Pool. Im
Dedicated- und Eigenbetrieb verwaltet es dedizierte, vertraglich zugesicherte
Kapazität. SSF erzwingt Runtime-Limits und liefert verdichtete Verbrauchs- und
Metrikereignisse zurück.

### 5. Betrieb, Monitoring und Support

Die Plattformansicht braucht ein SSF-Betriebscockpit mit:

- Verfügbarkeit, Fehlerrate, Ende-zu-Ende-Latenz und Queue-Zeit,
- Auslastung von GPU, CPU, Speicher, Warteschlangen und Provider-Abhängigkeiten,
- Mandantenbezogener Nutzung und Limitstatus ohne Gesprächsinhalte,
- Alarmen, Incidents, Wartungsfenstern und Konfigurations-/Provisionierungsdrift,
- kontrolliertem Supportzugriff mit Ticket, Begründung, Dauer, Reauth,
  widerrufbarer Freigabe und Audit-Nachweis.

Studio kann vorhandene Observability-Daten über eine sichere, aggregierte API
oder freigegebene Dashboard-Links darstellen. Es speichert keine rohen
Gesprächsinhalte in Monitoring oder Audit.

### 6. Datenschutz und Mandantenlebenszyklus

Studio orchestriert die administrativen Schritte der SSF-Customer-Journey:

- Anlegen, technische Abnahme und Übergabe an den Mandanten-Admin,
- Pausieren mit Sperrung neuer Sessions und Integrationen,
- Datenexport mit Berechtigungs- und Ablaufkontrolle,
- Lösch- oder Anonymisierungsauftrag nach vereinbarten Fristen,
- endgültige Stilllegung erst nach SSF-Bestätigung, Token-Widerruf und
  append-only Audit-Nachweis.

Gesprächsinhalte werden standardmäßig nicht dauerhaft gespeichert. Wenn ein
Mandant eine zulässige Speicherung aktiviert, verwaltet Studio den Richtlinien-
Sollzustand; SSF setzt ihn für die Runtime-Daten durch.

## APIs und Ereignisse

Die Integration benötigt eine versionierte Control-Plane-API mit mindestens:

| Richtung | Vertrag |
| --- | --- |
| Studio → SSF | Tenant anlegen, konfigurieren, aktivieren, pausieren, Ressourcen setzen, Export/Löschung anfordern. |
| SSF → Studio | Provisionierungsstatus, Konfigurationsstatus, Nutzungsaggregate, Limitverletzungen, Runtime-Health und Löschbestätigung. |
| Studio → SSF | Signierter Identitäts- und Tenant-Kontext für administrative SSF-Aufrufe. |
| SSF → Studio | Auditierbare Referenzen und Korrelationen, jedoch keine Gesprächsinhalte oder personenbezogenen Rohdaten. |

Alle Mutationen verwenden einen Idempotenzschlüssel, eine Korrelation und einen
expliziten erwarteten Zustand. Fehler sind stabil klassifiziert; ein unbekannter
oder widersprüchlicher Tenant-Kontext führt in SSF zu einer fail-closed-Ablehnung.

## Bedienoberfläche

Die Navigation bleibt nach Scope getrennt:

- **Platform:** SSF-Mandanten, Ressourcenpool, Betriebsübersicht, Incidents,
  globale Modelle/Provider und Supportfälle.
- **Mandant:** SSF-Einstellungen, operative Benutzer, lokale Nutzung,
  Datenrichtlinien, Integrationen und eigene Supportfälle.
- **Operativ:** Deep Link zur SSF-Gesprächsanwendung; Studio wird nicht zur
  zweiten Gesprächsoberfläche.

Die UI zeigt ausschließlich Aktionen, die der aktuelle Scope und die effektiven
Permissions erlauben. Sie ist keine Sicherheitsgrenze; Studio und SSF prüfen
die Berechtigung jeweils serverseitig.

## Nicht Bestandteil von Studio

Nicht in Studio implementiert werden:

- Audioaufnahme, WebSocket-Kommunikation und Echtzeit-Sessionführung,
- ASR-, Übersetzungs- und TTS-Ausführung,
- Speicherung oder Darstellung von Gesprächsinhalten im Standardfall,
- eigenständige, von SSF abweichende Quoten- oder Berechtigungsdurchsetzung.

## Umsetzungsreihenfolge

1. Tenant-Identität, Rollenabbildung und den versionierten Studio–SSF-Vertrag
   verbindlich spezifizieren.
2. Provisionierung, Statusrückmeldung und tenant-sichere Authentifizierung
   umsetzen und mit mindestens zwei Mandanten testen.
3. Mandantenansicht für SSF-Konfiguration und operative Benutzer bereitstellen.
4. Ressourcen-/Nutzungsaggregation und Runtime-Limitdurchsetzung ergänzen.
5. Betriebscockpit, Supportfreigabe sowie Export-/Löschworkflow ergänzen.

Jede Stufe muss Mandantenisolation, Auditierbarkeit, Idempotenz und eine klare
Fehlerbehandlung nachweisen, bevor sie für mehrere Organisationen freigegeben
wird.
