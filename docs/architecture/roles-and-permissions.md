# Rollen- und Berechtigungsmodell

## Zweck und Status

Dieses Dokument beschreibt das Zielbild einer mandantenfähigen, mehrstufigen
Rollenverwaltung für Smart Speech Flow (SSF). Es trennt die Systemverwaltung
von der Mandantenverwaltung und der operativen Gesprächsführung.

**Aktueller Stand:** SSF kennt im Session-Workflow ausschließlich die beiden
Client-Typen `admin` und `customer`. Die Rollen `system_admin` und
`tenant_admin` sind ein fachliches Zielbild und noch nicht implementiert.

## Begriffe und Betriebsmodell

Ein **Mandant** ist eine logisch getrennte Organisation oder Organisationseinheit.
Die Rolle **Customer** bezeichnet dagegen ausschließlich den Gesprächsteilnehmer
einer Session; sie ist nicht gleichbedeutend mit dem Vertragspartner oder
Mandanten.

`system_admin` ist die Administratorrolle der jeweiligen SSF-Installation. Im
vollständigen Eigenbetrieb oder bei einem kommunalen Plattformanbieter nimmt
der Betreiber diese Rolle selbst wahr. In Managed-Modellen kann dies SVS oder
ein beauftragter Dienstleister sein. Die Rolle verwaltet nur diese Installation
und deren Mandanten – keine fremden SSF-Installationen.

## Abbildung in SVA Studio

Wenn SVA Studio als SSF-Control-Plane eingesetzt wird, bleiben die fachlichen
SSF-Rollen und die technischen Studio-Rollen bewusst getrennt:

| SSF-Fachrolle | Studio-Scope und technische Grundlage |
| --- | --- |
| `system_admin` | `platform`-Scope mit der Root-only-Rolle `instance_registry_admin` |
| `tenant_admin` | `instance`-Scope mit der tenantlokalen Studio-Rolle `system_admin` und SSF-Admin-Permissions |
| `admin` | `instance`-Scope mit gezielten `ssf.*`-Permissions |
| `customer` | Keine Studio-Identität; nur eine zeitlich begrenzte SSF-Sessionberechtigung |

Studio ist führend für administrative Identitäten, Mandanten und
Berechtigungen. SSF akzeptiert den Tenant-Kontext nur aus einem signierten
Studio-/OIDC-Kontext oder einer serverseitigen Introspection. Eine vom Client
frei angegebene Mandanten-ID ist niemals vertrauenswürdig.

For the deliberately prioritised Control Plane Foundation, the root system
administrator creates tenants and their initial tenant administrators but does
not perform routine cross-tenant user administration. Tenant administrators
manage users and roles only in their own tenant realm. Root rights grant no
tenant-local rights, and tenant roles grant no root rights. A future support
or recovery path is a separately authorised, time-limited, fully audited
exception and is not part of the first delivery slice.

## Geltungsbereiche

Eine Berechtigung gilt immer in einem klaren Bereich (Scope):

| Scope | Bedeutung |
| --- | --- |
| System | Alle Mandanten und die globale SSF-Installation. |
| Mandant | Ein organisatorischer Kunde inklusive seiner Benutzer, Konfiguration und Ressourcen. |
| Session | Eine konkrete Unterhaltung zwischen einem operativen Admin und einem Customer. |
| Eigene Daten | Das Profil und die eigenen Sitzungen eines Benutzers. |

Eine Rolle in einem engeren Scope darf niemals Daten oder Einstellungen eines
übergeordneten Scopes verändern.

## Rollen

### 1. System-Admin (`system_admin`)

Der System-Admin betreibt die jeweilige SSF-Installation mandantenübergreifend. Er nimmt nicht am
fachlichen Gespräch einer Session teil und erhält keinen pauschalen Zugriff auf
deren Inhalte.

**Aufgaben und Funktionen**

- Own the root-level tenant lifecycle and the initial tenant administrator.
- Operate root-only plugin activation, provisioning, reconciliation, readiness,
  and audit capabilities.
- Later stages may add quotas, global configuration, operations dashboards,
  support, reporting, and lifecycle/privacy workflows; they are not part of
  the initial Control Plane Foundation.

### 2. Mandanten-Admin (`tenant_admin`)

Der Mandanten-Admin verwaltet einen einzelnen Mandanten. Er ist die fachliche
und organisatorische Ansprechperson des Kunden, jedoch kein Plattformbetreiber.

**Aufgaben und Funktionen**

- Benutzer seines Mandanten einladen, deaktivieren und Rollen zuweisen.
- Operative Admins verwalten und bei Bedarf den Zugang entziehen.
- In later stages, manage branding, language, integration, resources,
  reporting, retention, and support settings within global policies.

**Nicht erlaubt:** andere Mandanten, globale Sicherheitsrichtlinien,
plattformweite Modelle oder globale Betriebsparameter verwalten.

### 3. Operativer Admin (`admin`)

Der operative Admin führt Gespräche mit Customers und nutzt SSF in der
fachlichen Arbeit. Dies entspricht dem heutigen `admin`-Client-Typ.

**Aufgaben und Funktionen**

- Eigene Sessions erstellen, starten, beenden und verwalten.
- Mit dem zugeordneten Customer per Text und Audio kommunizieren.
- Übersetzungs- und Gesprächsfunktionen innerhalb der Session nutzen.
- Eigene beziehungsweise freigegebene Session-Verläufe einsehen, sofern die
  Mandantenrichtlinie dies erlaubt und die Inhalte überhaupt gespeichert werden.
- Das eigene Profil, die bevorzugte Sprache und persönliche Benachrichtigungen
verwalten.

**Nicht erlaubt:** Benutzer, Rollen, globale oder mandantenweite Ressourcen
und Einstellungen verwalten.

### 4. Customer (`customer`)

Der Customer ist der externe Gesprächsteilnehmer einer Session. Dies entspricht
dem heutigen `customer`-Client-Typ. Ein Customer kann anonym, per einmaligem
Einladungslink oder mit einem eingeschränkten Benutzerkonto teilnehmen.

**Aufgaben und Funktionen**

- Einer zugewiesenen Session beitreten und an ihr teilnehmen.
- Text- und Audionachrichten senden und empfangen.
- Die für die Session erlaubte Sprache auswählen.
- Eigene Einwilligungen erteilen oder widerrufen, soweit dies den
Sessionzugang nicht ausschließt.
- Bei einem registrierten Konto: Profil- und Datenschutzeinstellungen verwalten.

Sessioninhalte werden standardmäßig nicht dauerhaft gespeichert. Soweit ein
Mandant eine Speicherung aktiviert, gelten dafür seine Aufbewahrungs- und
Löschrichtlinien innerhalb der globalen Vorgaben.

**Nicht erlaubt:** andere Sessions, andere Customers, Benutzer- oder
Mandantendaten einsehen oder verändern.

## Berechtigungsmatrix

| Funktion | System-Admin | Mandanten-Admin | Operativer Admin | Customer |
| --- | :---: | :---: | :---: | :---: |
| Mandanten verwalten | Ja | Nein | Nein | Nein |
| Benutzer im eigenen Mandanten verwalten | Nein (initial tenant admin only) | Ja | Nein | Nein |
| Globale Sicherheits- und Systemrichtlinien verwalten | Later stage | Nein | Nein | Nein |
| Mandanteneinstellungen verwalten | Tenant lifecycle only | Later stage | Nein | Nein |
| Ressourcen und Kontingente zuweisen | Later stage | Later stage | Nein | Nein |
| Plattformmonitoring und Incident-Management | Later stage | Later stage | Nein | Nein |
| Mandanten-Audit-Logs einsehen | Audit scope | Audit scope | Own actions | Own actions |
| Session erstellen and lead | No | Optional | Yes | No |
| Join an assigned session | No | Optional | Yes | Yes |
| View conversation content | Later-stage, authorised exception | Later-stage tenant policy | Assigned sessions | Own session |

Conversation-content access and support are later-stage capabilities; they are
not part of the first delivery slice.

## First Delivery Boundary

The first Control Plane delivery provides tenant provisioning and status,
tenant-local IAM, SSF plugin activation, an SSF plugin database and baseline
record, a minimal internal configuration API, audit, reconciliation, and
readiness. It excludes ClickHouse and session-data analytics, conversation
content, usage and cost reports, and support access.

## Benötigte Produktfunktionen

Damit diese Rollen praktisch nutzbar und sicher durchsetzbar sind, braucht SSF:

- **Identitäten und Mitgliedschaften:** Benutzerkonten, Mandantenmitgliedschaften,
  Einladungen sowie Deaktivierung und Reaktivierung.
- **Rollen- und Scope-Prüfung:** zentrale Autorisierung für API, WebSocket und
  Hintergrundaufgaben; jede Anfrage wird gegen Rolle und Mandant geprüft.
- **Mandantenisolation:** Mandanten-ID an allen relevanten Datenobjekten,
  Abfragen und Speichern; keine mandantenübergreifenden Standardabfragen.
- **Ressourcenverwaltung (later stage):** Quoten, Verbrauchsmessung, Warnschwellen und
  Durchsetzung von Limits; Pooling nur in Multi-Tenant-Installationen,
  dedizierte Zuteilung in Dedicated- und Eigenbetriebsmodellen.
- **Admin-Oberflächen und APIs:** getrennte Ansichten für Systemverwaltung,
  Mandantenverwaltung und operative Sessionarbeit.
- **Audit-Logging:** unveränderbare, durchsuchbare Protokolle für Anmeldungen,
  Rollenänderungen, Konfigurationsänderungen, Supportzugriffe und Datenexporte.
- **Sicherheitsfunktionen:** MFA, sichere Passwort- bzw. SSO-Anmeldung,
  Sitzungsverwaltung, Rechteentzug und Secret-/API-Key-Verwaltung.
- **Monitoring und Alarmierung (later stage):** technische und fachliche Kennzahlen,
  Grenzwerte, Benachrichtigungen sowie Incident- und Wartungsprotokolle.
- **Datenschutzfunktionen (later stage):** Einwilligungen, Datenexport, Löschung,
  Aufbewahrungsfristen und kontrollierter Supportzugriff.
- **Control-Plane-Integration:** versionierte, idempotente APIs and events for
  provisioning, baseline configuration, reconciliation, readiness, and runtime
  status; Studio and SSF have no shared domain database. Resource aggregates
  and deletion confirmations are later-stage contracts.

## Sicherheitsprinzipien

1. **Least Privilege:** Jede Rolle erhält nur die minimal erforderlichen Rechte.
2. **Mandantentrennung:** Daten eines Mandanten sind für andere Mandanten nie
   sichtbar oder veränderbar.
3. **Trennung von Betrieb und Inhalt:** Systembetrieb und Gesprächsinhalte
   bleiben getrennt; Ausnahmezugriffe sind explizit, begründet und auditiert.
4. **Nachvollziehbarkeit:** Jede privilegierte Aktion wird mit Akteur, Zeit,
   Scope, Aktion und Ergebnis protokolliert.
5. **Explizite Rechteprüfung:** Das Frontend verbessert die Bedienung, ist aber
   keine Sicherheitsgrenze; die Durchsetzung erfolgt serverseitig.

## Erweiterungsoptionen

Bei wachsendem Funktionsumfang können weitere, gezielt eingeschränkte Rollen
ergänzt werden:

- `auditor`: Nur-Lesezugriff auf Audit- und Compliance-Berichte eines Mandanten.
- `support_agent`: zeitlich begrenzter, freigegebener Supportzugriff ohne
  Verwaltungsrechte.
- `billing_manager`: Zugriff auf Verbrauch, Rechnungen und Zahlungsdaten ohne
  Zugriff auf Gesprächsinhalte oder Benutzerverwaltung.

Diese Rollen sollten erst eingeführt werden, wenn ein konkreter fachlicher
Bedarf besteht; sie sind keine Voraussetzung für die erste Ausbaustufe.
