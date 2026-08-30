# Customer Journey über den Mandantenlebenszyklus

## Zweck und Status

Dieses Dokument beschreibt das Zielbild für den vollständigen Lebenszyklus eines SSF-Mandanten. Es zeigt, wie `system_admin`, `tenant_admin`, `admin` und `customer` vom ersten Setup bis zur Abschaltung zusammenwirken.

Es ergänzt das [Rollen- und Berechtigungsmodell](roles-and-permissions.md). Die beschriebenen Mandanten- und Verwaltungsfunktionen sind ein Zielbild; im aktuellen SSF-Session-Workflow existieren technisch nur `admin` und `customer`.

Ein Mandant ist der organisatorische Kunde bzw. eine Organisationseinheit. Der `customer` ist ausschließlich der Gesprächsteilnehmer einer Session. Der `system_admin` gehört zum Betreiber der jeweiligen SSF-Installation: je nach Betriebsmodell also zu SVS, dem Kunden selbst oder einem kommunalen Plattformanbieter.

Wenn SVA Studio als Control Plane eingesetzt wird, erledigt der Betreiber die
Schritte zur Mandanten-, Benutzer-, Ressourcen- und Lifecycle-Verwaltung in
Studio. SSF bestätigt Provisionierung, Konfigurationsanwendung,
Runtime-Gesundheit und Löschvorgänge über versionierte APIs bzw. Ereignisse.

The current Control Plane Foundation covers tenant provisioning, tenant-local
user and role administration, plugin activation, audit, reconciliation, and
readiness only. Resources, support, export, deletion, and the broader
lifecycle described below remain target capabilities for later stages.

## Beteiligte Rollen

| Rolle | Verantwortungsbereich in der Journey |
| --- | --- |
| System-Admin | Plattformbetrieb, Mandantenbereitstellung, Sicherheit, Ressourcen und kontrollierter Support. |
| Mandanten-Admin | Übernahme und Konfiguration des eigenen Mandanten, Benutzerverwaltung und fachliche Verantwortung. |
| Operativer Admin | Durchführung konkreter Gespräche bzw. Servicesitzungen. |
| Customer | Teilnahme an einer ihm zugewiesenen Session. |

## Lebenszyklus auf einen Blick

```text
Plattform bereit
      ↓
Mandant bereitstellen → Mandant übernehmen → Nutzer einrichten
      ↓                                         ↓
      └──────────── Betrieb und Support ← Sessions durchführen
      ↓
Vertrag / Nutzung endet → Daten exportieren und löschen → Mandant abschalten
```

## 1. Plattform initial einrichten

**Ziel:** SSF ist als sichere, beobachtbare Plattform betriebsbereit, bevor ein Kunde angelegt wird.

| Akteur | Handlung | Ergebnis |
| --- | --- | --- |
| System-Admin | Infrastruktur, Datenbanken, Monitoring, Backups, Alarmierung und Incident-Prozess einrichten. | Ein überwachter, wiederherstellbarer Betrieb ist möglich. |
| System-Admin | Globale Sicherheitsstandards definieren: Authentifizierung, MFA/SSO, Passwort- und Sitzungsrichtlinien, Audit-Logging. | Einheitliche Sicherheitsgrundlage. |
| System-Admin | Verfügbare Sprachen, Modelle, Integrationen, Service-Limits und Standard-Aufbewahrungsregeln konfigurieren. | Ein kontrolliertes Produktangebot ist definiert. |

**Kontrollpunkt:** Ein Betriebs- und Sicherheitscheck bestätigt Verfügbarkeit, Backup-Wiederherstellbarkeit und Alarmwege.

## 2. Mandant anlegen und vorbereiten

**Auslöser:** Eine Organisation hat SSF beauftragt, wird durch einen Plattformanbieter angebunden oder erhält einen Testzugang.

| Akteur | Handlung | Ergebnis |
| --- | --- | --- |
| System-Admin | Legt den Mandanten in der Studio-Control-Plane an und vergibt eindeutige Mandanten-ID, Vertrags-/Tarifmodell und Status. Studio fordert die technische SSF-Provisionierung an. | Isolierter Mandantenbereich existiert. |
| System-Admin | Ressourcen zuteilen: Benutzerplätze, Anfrage- und Sessionkontingent, Speicher, erlaubte Sprachen und Modellbudget. Bei Multi-Tenant-Betrieb geschieht dies aus einem gemeinsamen Pool, bei Dedicated- und Eigenbetrieb aus dedizierten Ressourcen. | Der Mandant kann innerhalb klarer Grenzen arbeiten. |
| System-Admin | Lädt über Studio einen ersten Mandanten-Admin ein und erzwingt sichere Erstanmeldung. | Die Organisation erhält einen verantwortlichen Zugang. |
| System-Admin | Optional Branding, Region, SSO und vereinbarte Integrationen vorkonfigurieren. | Der Mandant ist für die Übergabe vorbereitet. |

**Kontrollpunkt:** Der System-Admin prüft, dass der neue Mandant weder Daten anderer Mandanten sehen noch globale Einstellungen verändern kann.

## 3. Mandant übernehmen und konfigurieren

**Ziel:** Der Kunde übernimmt die Verantwortung für seinen abgegrenzten Bereich.

| Akteur | Handlung | Ergebnis |
| --- | --- | --- |
| Mandanten-Admin | Einladung annehmen, MFA/SSO einrichten und eigene Kontaktdaten bestätigen. | Eine nachvollziehbare Kundenverantwortung ist etabliert. |
| Mandanten-Admin | Mandanteneinstellungen prüfen und konfigurieren: Name, Branding, Zeitzone, Benachrichtigungen, freigegebene Sprachen und erlaubte Integrationen. | SSF passt zum Einsatzkontext des Kunden. |
| Mandanten-Admin | Datenschutz- und Aufbewahrungseinstellungen innerhalb der globalen Vorgaben festlegen; ohne ausdrückliche Aktivierung werden Gesprächsinhalte nicht dauerhaft gespeichert. | Datenverarbeitung entspricht der Kundenvereinbarung. |
| Mandanten-Admin | Interne Verantwortlichkeiten, Supportprozess und Schulung organisieren. | Der operative Start ist vorbereitet. |

**Kontrollpunkt:** Der Mandanten-Admin bestätigt Konfiguration und Ansprechpartner; der System-Admin dokumentiert die erfolgreiche Übergabe.

## 4. Benutzer und Teams einrichten

**Ziel:** Nur berechtigte Personen bekommen den für ihre Arbeit notwendigen Zugang.

| Akteur | Handlung | Ergebnis |
| --- | --- | --- |
| Mandanten-Admin | Lädt operative Admins über Studio ein, deaktiviert sie und ordnet bei Bedarf Teams/Standorte zu. | Arbeitsfähige Benutzerbasis. |
| Mandanten-Admin | Rollen ausschließlich nach dem Minimalprinzip vergeben. | Keine unnötigen Verwaltungsrechte. |
| Operativer Admin | Einladung annehmen, Konto absichern und persönliche Spracheinstellungen setzen. | Einsatzbereiter Gesprächsarbeitsplatz. |
| System-Admin | Überwacht Lizenz-/Ressourcengrenzen und unterstützt nur mit expliziter Freigabe. | Skalierbarer Betrieb ohne ungeprüften Datenzugriff. |

**Kontrollpunkt:** Rollenänderungen, Einladungen, Deaktivierungen und Anmeldungen werden im Audit-Log aufgezeichnet.

## 5. Operative Nutzung: Session durchführen

**Ziel:** Ein Customer erhält einen möglichst einfachen Zugang zu einer übersetzten bzw. unterstützten Unterhaltung.

| Akteur | Handlung | Ergebnis |
| --- | --- | --- |
| Operativer Admin | Erstellt eine Session und lädt den Customer ein, zum Beispiel per Link oder Code. | Eine zeitlich und fachlich zugeordnete Session ist bereit. |
| Customer | Öffnet den Link/Code, wählt gegebenenfalls die Sprache und bestätigt erforderliche Einwilligungen. | Customer tritt der zugewiesenen Session bei. |
| Operativer Admin und Customer | Führen die Text- und/oder Audiokommunikation durch. | Nachrichten werden innerhalb der Session verarbeitet und zugestellt. |
| Operativer Admin | Beendet die Session und dokumentiert bei Bedarf das Ergebnis im organisationsinternen Prozess. | Die Unterhaltung ist abgeschlossen. |

**Erlebnisprinzip:** Für den Customer soll kein umfangreiches Konto nötig sein. Ein zeitlich begrenzter Einladungslink oder Code senkt die Einstiegshürde, ohne die Mandanten- und Sessiongrenzen aufzugeben.

## 6. Laufender Betrieb und Support

**Ziel:** Der Kunde arbeitet eigenständig; die Plattform bleibt sicher, verfügbar und beobachtbar.

| Akteur | Handlung | Ergebnis |
| --- | --- | --- |
| Mandanten-Admin | Prüft Nutzung, Benutzer, Kontingente und Audit-Ereignisse des eigenen Mandanten. | Frühzeitige Reaktion auf fachliche oder organisatorische Probleme. |
| System-Admin | Überwacht Verfügbarkeit, Latenzen, Fehlerraten, Kapazität, Kosten und Sicherheitsalarme über alle Mandanten hinweg. | Betriebsprobleme werden früh erkannt. |
| Mandanten-Admin | Erstellt bei Problemen einen Supportfall und gibt nur die nötigen Diagnosedaten frei. | Support ist nachvollziehbar beauftragt. |
| System-Admin | Führt den in Studio freigegebenen Diagnose- oder Supportzugriff zeitlich begrenzt, zweckgebunden und auditiert aus. | Problembehebung ohne pauschalen Zugriff auf Kundendaten. |
| System-Admin | Steuert Wartungen, Updates, Backups und Incidents; informiert betroffene Mandanten. | Planbarer und belastbarer Betrieb. |

## 7. Skalierung und Änderung während der Laufzeit

**Auslöser:** Der Kunde wächst, reduziert Nutzung oder benötigt neue Funktionen.

| Akteur | Handlung | Ergebnis |
| --- | --- | --- |
| Mandanten-Admin | Beantragt zusätzliche Benutzerplätze, Kontingente, Sprachen oder Integrationen. | Der Bedarf ist fachlich dokumentiert. |
| System-Admin | Prüft vereinbarte Leistung, Kapazität, Sicherheit und Kosten; passt Ressourcen bzw. Features an. | Änderungen bleiben kontrolliert und abrechenbar. |
| Mandanten-Admin | Richtet neue operative Admins ein und passt interne Prozesse an. | Die Organisation kann den erweiterten Umfang nutzen. |

**Kontrollpunkt:** Ressourcenänderungen müssen wirksam ab einem klaren Zeitpunkt gelten und im Audit- sowie Verbrauchsprotokoll erscheinen.

## 8. Mandant pausieren oder abschalten

**Auslöser:** Vertragsende, Kündigung, Ende einer internen Bereitstellung, auslaufender Testzugang oder eine beauftragte vorübergehende Pause.

### 8.1 Pausieren

| Akteur | Handlung | Ergebnis |
| --- | --- | --- |
| Mandanten-Admin oder System-Admin | Mandant auf `suspended` setzen und neue Sessions verhindern. | Kein neuer Verbrauch, Daten bleiben gemäß Frist erhalten. |
| System-Admin | Zugriffe, Tokens und Integrationen sperren; Aufbewahrungsfrist und Reaktivierungsprozess festhalten. | Sicherer, reversibler Zustand. |

### 8.2 Geordnete Abschaltung

| Akteur | Handlung | Ergebnis |
| --- | --- | --- |
| Mandanten-Admin | Kündigung bestätigen, Datenexport beantragen und Ansprechpartner für Rückfragen benennen. | Kundenentscheidung ist nachvollziehbar. |
| System-Admin | Mandant sperren, aktive Sessions kontrolliert beenden und Zugänge/Integrationen widerrufen. | Keine weitere Verarbeitung im Mandanten. |
| System-Admin | Stößt den vereinbarten Datenexport über Studio an; SSF stellt ihn bereit und bestätigt Abschluss sowie sicheren Abruf. | Kunde kann seine Daten übernehmen. |
| System-Admin | Stößt Löschung oder Anonymisierung über Studio an; SSF führt sie nach Ablauf der Aufbewahrungsfristen aus und bereinigt Backups nach der definierten Backup-Rotation. | Datenschutzkonformer Abschluss. |
| System-Admin | Löschung bzw. Anonymisierung und Abschluss im Audit-Log dokumentieren. | Abschaltung ist nachweisbar. |

**Kontrollpunkt:** Ein Mandant gilt erst als vollständig abgeschaltet, wenn Zugänge, Tokens und Integrationen widerrufen sowie Datenexport, Löschung und Audit-Nachweis abgeschlossen sind.

## Wesentliche Übergaben

| Übergabe | Verantwortlich | Nachweis |
| --- | --- | --- |
| Plattform → neuer Mandant | System-Admin | Mandantenanlage, Sicherheits- und Isolationscheck. |
| System-Admin → Mandanten-Admin | Beide | Akzeptierte Einladung und bestätigte Konfiguration. |
| Mandanten-Admin → operative Admins | Mandanten-Admin | Rollenvergabe und erfolgreiche Kontoaktivierung. |
| Operativer Admin → Customer | Operativer Admin | Gültige, auf die Session beschränkte Einladung. |
| Mandant → System-Admin bei Support | Mandanten-Admin | Supportfall und explizite, zeitlich begrenzte Freigabe. |
| Aktiver Mandant → Abschaltung | Beide | Export-/Löschauftrag und Abschaltprotokoll. |

## Messgrößen für eine gute Journey

- Zeit von Mandantenanlage bis zur ersten erfolgreichen Session.
- Anteil der Mandanten, die Benutzer ohne System-Admin-Support verwalten.
- Anteil erfolgreicher Customer-Beitritte beim ersten Versuch.
- Anzahl und Dauer von Supportzugriffen pro Mandant.
- Ressourcenverbrauch, Grenzwertüberschreitungen und Kosten pro Mandant.
- Zeit bis zur vollständigen Sperrung bzw. Löschung nach Vertragsende.

Diese Messgrößen verbinden Skalierbarkeit mit Bedienbarkeit: Je weniger manuelle Eingriffe des System-Admins nötig sind und je zuverlässiger Customers einer Session beitreten, desto besser erfüllt SSF sein Produktziel.
