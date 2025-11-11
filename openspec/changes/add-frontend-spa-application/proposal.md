# Change: Add Frontend Single-Page Application

## Why

Das Projekt benötigt eine vollständige Frontend-Anwendung, die sowohl für interne Verwaltungsmitarbeiter (Admin) als auch für externe Bürger (Kunde) als einheitlicher Einstiegspunkt dient. Aktuell existiert nur ein archivierter Frontend-Prototyp (`frontend-archive` Service), der aus einem separaten Repository gebaut wird.

Die neue Frontend-Anwendung soll:
- Als zentraler Einstieg für beide Benutzergruppen dienen (mit optionalem Passwortschutz)
- Die Session-Management-Workflows für Admin und Kunde implementieren
- Bidirektionale Echtzeit-Kommunikation über WebSocket (mit Polling-Fallback) ermöglichen
- Audio- und Texteingabe für Nachrichten unterstützen
- Eine moderne, responsive Benutzeroberfläche mit React/TypeScript bereitstellen

## What Changes

- **Neuer Frontend-Service** in `services/frontend/` mit vollständiger React/TypeScript-Anwendung
- **Routing-Struktur**:
  - `/` - Passwort-geschützte Landing-Page (optional, siehe Design-Entscheidung unten)
  - `/admin` - Admin-Interface für Session-Erstellung und Kommunikation
  - `/customer` oder `/join/{sessionId}` - Kunden-Interface für Session-Aktivierung und Kommunikation
- **Session-Management-Integration**:
  - Admin erstellt Sessions über `POST /api/admin/session/create`
  - Kunde aktiviert Session über `POST /api/customer/session/activate` mit Sprachauswahl
  - Beide Seiten zeigen Session-Status und ermöglichen Wechsel/Beendigung
- **Kommunikations-Interface**:
  - Toggle zwischen Audio-Aufnahme (WebRTC) und Texteingabe
  - Sofortige Bubble-Anzeige mit Pulsierungs-Indikator bei Nachrichtenversand
  - WebSocket-Integration für Echtzeit-Updates (mit Polling-Fallback)
  - Anzeige aller Pipeline-Metadaten (Processing-Zeit, Sprachen, ASR/Translation/TTS-Infos)
- **Docker-Integration**:
  - Build-Setup mit Nginx für statisches Hosting
  - Traefik-Labels für `translate.smart-village.solutions`
  - Environment-Variablen für API-Base-URL und WebSocket-Endpunkte

## Impact

**Affected Specs:**
- `frontend-application` (NEW) - Komplette Spezifikation der Frontend-Anwendung

**Affected Code:**
- `services/frontend/` - Neue Verzeichnisstruktur mit React-App
- `services/frontend/Dockerfile` - Ersetzt aktuellen Platzhalter-Dockerfile
- `docker-compose.yml` - Bereits vorbereitet, keine Änderungen nötig

**Backend-API Dependencies:**
- Nutzt bestehende Endpunkte: `/api/admin/session/create`, `/api/customer/session/activate`, `/api/session/{id}/message`, `/api/languages/supported`, `/ws/{sessionId}/{clientType}`
- Keine Backend-Änderungen erforderlich

## Design-Entscheidungen & Backend-Abweichungen

### ✅ Bestätigt durch Backend-API

1. **Session-Erstellung durch Admin**: `POST /api/admin/session/create` existiert und liefert Session-ID + Join-URL
2. **Kunden-Aktivierung mit Sprachauswahl**: `POST /api/customer/session/activate` mit `session_id` + `customer_language` verfügbar
3. **Unified Message Endpoint**: `POST /api/session/{id}/message` akzeptiert Audio (multipart) und Text (JSON)
4. **WebSocket-Kommunikation**: `wss://ssf.smart-village.solutions/ws/{sessionId}/{clientType}` implementiert
5. **Supported Languages**: `GET /api/languages/supported` vorhanden
6. **Pipeline-Metadaten**: Backend liefert vollständige `pipeline_metadata` in allen Message-Responses

### ⚠️ Anpassungen an Original-Anforderungen

#### 1. Passwortschutz (Passwort: ssf2025kassel)

**Original-Anforderung:** "Allgemeine Einleitungsseite mit der Abfrage eines Passworts (ssf2025kassel)"

**Backend-Status:** ❌ Kein Backend-Endpunkt für Passwort-Authentifizierung vorhanden

**Empfohlene Implementierung:**
- **Option A (Frontend-Only):** Passwort-Check nur im Frontend (localStorage/SessionStorage), kein Backend-Call
  - ✅ Schnell implementierbar
  - ⚠️ Bietet nur rudimentären Schutz (clientseitig umgehbar)
  - ✅ Ausreichend für interne Nutzung/Präsentationszwecke
- **Option B (Skip):** Landing-Page entfernen, direkt zu `/admin` oder `/customer` routen
  - ✅ Einfachste Lösung
  - ⚠️ Keine zentrale Einstiegsseite
  - ✅ Backend benötigt keine Änderungen

**Vorschlag:** Option A (Frontend-Only-Check) für MVP, später durch echte Backend-Authentifizierung ersetzbar

#### 2. Session-Aktivierung durch Kunde

**Original-Anforderung:** "Kundenseite zeigt eine Eingabe der Session-ID"

**Backend-Status:** ✅ Funktioniert genau wie gewünscht

**Tatsächliches Verhalten:**
- Kunde navigiert zu `/customer` Seite
- Kunde gibt 8-stellige Session-ID manuell ein (z.B. "ABC12345")
- Frontend validiert Session-ID-Format (8 Zeichen, Uppercase)
- Frontend verifiziert Session-Existenz über Backend
- Kunde wählt Sprache aus Dropdown (API: `GET /api/languages/supported`)
- Frontend sendet `POST /api/customer/session/activate` mit `{session_id, customer_language}`
- Session wechselt von `pending` → `active`

**Zusätzlich unterstützt:** URL-Routing (`/join/{sessionId}`) für QR-Code-Szenarien, aber primär ist manuelle Eingabe

#### 3. Session-Wechsel & Beendigung

**Original-Anforderung:** "Beide haben die Möglichkeit die Session zu ändern, was dann zurück zu Session erstellen bzw. Session id eingeben zurück führt"

**Backend-Status:** ⚠️ Teilweise vorhanden

**Verfügbare Backend-Endpunkte:**
- `DELETE /api/admin/session/{sessionId}/terminate` - Admin kann Session beenden
- ❌ Kein expliziter "Session wechseln" Endpunkt

**Empfohlene Implementierung:**
- **Admin:** Button "Neue Session erstellen" → leitet zu Session-Erstellungs-View weiter
- **Admin:** Button "Session beenden" → `DELETE /api/admin/session/{id}/terminate` → zurück zu Start
- **Kunde:** Button "Zurück" → Frontend-Navigation zu `/customer` (neue Session-ID-Eingabe)
- **Beide:** WebSocket empfängt `session_terminated` Event → automatische Weiterleitung

#### 4. Message-Anzeige & Metadaten

**Original-Anforderung:** "Wenn das Backend reagiert, zeige beim Kunden UND beim Intern die Message an (inkl. aller Metadaten)"

**Backend-Status:** ✅ Vollständig implementiert mit wichtiger Unterscheidung

**WebSocket-Message-Flow:**
Wenn eine Nachricht über `POST /api/session/{id}/message` gesendet wird, sendet das Backend **zwei separate WebSocket-Nachrichten**:

1. **Sender Confirmation** (role: `"sender_confirmation"`):
   - An den **ursprünglichen Sender** (Admin oder Kunde)
   - Zeigt die **ASR-erkannte** oder eingegebene Original-Nachricht
   - Dient zur Bestätigung der Eingabe
   - Kann ignoriert werden, wenn Frontend optimistic UI verwendet

2. **Receiver Message** (role: `"receiver_message"`):
   - An den **Gesprächspartner** (andere Seite)
   - Zeigt die **übersetzte** Nachricht
   - Enthält Audio-URL für TTS-Ausgabe
   - **MUSS** vom Frontend angezeigt werden

**Frontend-Implementierung:**
```typescript
websocket.onmessage = (event) => {
  const msg = JSON.parse(event.data);

  if (msg.role === "sender_confirmation") {
    // Optional: Bestätigung für Sender anzeigen
    // Oder: Ignorieren, wenn optimistic UI verwendet wird
  }

  if (msg.role === "receiver_message") {
    // WICHTIG: Übersetzte Nachricht für Empfänger anzeigen
    addMessageBubble({
      text: msg.translation,
      audioUrl: msg.audio_url,
      metadata: msg.pipeline_metadata
    });
    playAudio(msg.audio_url); // Automatisch abspielen
  }
};
```

#### 5. Bubble mit Pulsierungs-Indikator

**Original-Anforderung:** "Nach Versand wird sofort ein Bubble angezeigt, in der drei Punkte pulsieren"

**Backend-Status:** ✅ Frontend-Implementierung möglich

**Empfohlener Flow:**
1. User sendet Nachricht (Audio oder Text)
2. Frontend zeigt **sofort** optimistische Bubble mit Pulsierungs-Indikator ("...")
3. `POST /api/session/{id}/message` wird abgeschickt
4. WebSocket empfängt `receiver_message` mit fertiger Übersetzung
5. Frontend ersetzt Pulsierungs-Bubble durch finale Nachricht

**Technische Details:**
- WebSocket-Latenz: < 100ms nach Backend-Verarbeitung
- Gesamte Pipeline-Zeit: ~2-5 Sekunden (ASR + Translation + TTS)
- Pulsierungs-Animation während der gesamten Verarbeitungszeit

## Migration Plan

### Phase 1: Grundgerüst & Routing (Tag 1-2)
1. React/TypeScript-Projekt mit Vite aufsetzen
2. Routing-Struktur implementieren (`/`, `/admin`, `/customer`, `/join/:id`)
3. Basis-Layout-Komponenten (Header, Container, Navigation)
4. Docker-Build mit Nginx konfigurieren

### Phase 2: Session-Management (Tag 3-4)
5. Admin-Session-Erstellung (API-Integration)
6. Kunden-Session-Aktivierung mit Sprachauswahl
7. Session-Status-Anzeige und Polling
8. Session-Beendigung/-Wechsel

### Phase 3: Kommunikations-Interface (Tag 5-7)
9. Audio-Aufnahme mit WebRTC (MediaRecorder API)
10. Text-Eingabe-Komponente
11. Message-Versand über unified endpoint
12. Bubble-Anzeige mit Pulsierungs-Indikator
13. WebSocket-Integration für Echtzeit-Updates
14. Polling-Fallback für mobile Clients

### Phase 4: UI/UX-Polishing (Tag 8-9)
15. Responsive Design (Mobile-First)
16. Pipeline-Metadaten-Anzeige (Collapsible/Details)
17. Audio-Player-Komponente
18. Error-Handling & Loading-States
19. Accessibility (ARIA-Labels, Keyboard-Navigation)

### Phase 5: Testing & Deployment (Tag 10)
20. Unit-Tests für kritische Komponenten
21. Integration-Tests für API-Calls
22. E2E-Tests mit Playwright
23. Docker-Build testen und in `docker-compose.yml` integrieren

## Decisions on Open Questions

1. **Passwortschutz:** ✅ Frontend-Only (localStorage) für MVP
   - Passwort "ssf2025kassel" wird clientseitig in sessionStorage validiert
   - Später durch Backend-Authentifizierung ersetzbar

2. **Session-ID-Eingabe:** ✅ Manuelles Input-Feld auf `/customer` Seite
   - Kunde gibt 8-stellige Session-ID manuell ein
   - Wichtig: Seite läuft auf anderem Gerät, URL-Sharing nicht praktikabel
   - Input-Feld mit Validierung (8 Zeichen, Uppercase)
   - Zusätzlich: URL-Routing (`/join/{id}`) als Alternative für QR-Code-Szenarien

3. **Message-History:** ✅ Komplette Historie beim Session-Start laden
   - Frontend ruft `GET /api/session/{id}/messages` beim Component-Mount auf
   - Alle bisherigen Nachrichten werden chronologisch angezeigt
   - Auto-Scroll zum letzten Message

4. **Audio-Autoplay:** ✅ Automatisch abspielen
   - Übersetzte Audio wird sofort abgespielt bei Empfang
   - Browser-Policy: Erst nach User-Interaction möglich (erste Message erfordert Play-Button-Click)
   - Danach alle folgenden Messages automatisch

5. **Multi-Session-Support (Admin):** ⏳ Später (nicht im MVP)
   - MVP: Admin verwaltet eine Session zur Zeit
   - Feature-Request für spätere Phase
   - Architecture bereits vorbereitet (Session-ID-basiert)
