## Context

Das Smart Speech Flow Backend benötigt eine vollständige Frontend-Anwendung, die als zentrale Benutzeroberfläche für Admin-Mitarbeiter und Kunden dient. Das Frontend wird als Single-Page-Application (SPA) mit React/TypeScript entwickelt und über Docker containerisiert.

**Stakeholders:**
- Verwaltungsmitarbeiter (Admin): Deutschsprachig, erstellen Sessions und kommunizieren mit Bürgern
- Bürger (Kunden): Mehrsprachig, aktivieren Sessions und kommunizieren in ihrer Muttersprache
- System-Administratoren: Deployment und Wartung des Frontend-Containers

**Constraints:**
- Muss mit bestehendem Backend-API kompatibel sein (keine Backend-Änderungen)
- WebSocket-Kommunikation muss durch Traefik-Proxy funktionieren
- Responsive Design für Mobile-First-Nutzung erforderlich
- Deployment über Docker Compose in bestehendes Setup

## Goals / Non-Goals

**Goals:**
- Vollständige UI-Implementierung für Admin- und Kunden-Workflows
- Echtzeit-Kommunikation über WebSocket mit Polling-Fallback
- Benutzerfreundliche Audio- und Texteingabe mit visuellen Feedback-Mechanismen
- Responsive Design für Desktop, Tablet und Mobile
- Containerisiertes Deployment mit Nginx als Static-File-Server

**Non-Goals:**
- Backend-API-Änderungen (Frontend nutzt bestehende Endpunkte)
- Native Mobile Apps (nur responsive Web-App)
- Server-Side Rendering (SSR) oder Static Site Generation (SSG)
- Komplexe Authentifizierung (nur optionaler Frontend-Passwortschutz)
- Offline-First-Funktionalität (Service Worker optional)

## Technical Decisions

### Decision 1: React + TypeScript + Vite

**Rationale:**
- React bietet etabliertes Ökosystem und gute Community-Support
- TypeScript erhöht Code-Qualität durch statische Typisierung
- Vite ermöglicht schnelle Entwicklung durch Hot-Module-Replacement
- Kompatibel mit bestehenden Testing-Tools (Vitest, Playwright)

**Alternatives Considered:**
- Vue.js: Weniger Ecosystem-Reife für komplexe WebSocket-Integration
- Svelte: Kleineres Ökosystem, weniger Third-Party-Libraries
- Plain JavaScript: Fehlende Typsicherheit für größeres Projekt

**Trade-offs:**
- Größeres Bundle-Size als Svelte (akzeptabel durch Code-Splitting)
- TypeScript erfordert initiale Lernkurve (amortisiert durch weniger Runtime-Fehler)

### Decision 2: Frontend-Only Passwortschutz

**Rationale:**
- Backend hat keine Authentifizierungs-Endpunkte implementiert
- Schnelle Implementierung ohne Backend-Änderungen möglich
- Ausreichend für MVP und interne Nutzung/Demos
- sessionStorage schützt vor versehentlichem Zugriff

**Alternatives Considered:**
- Backend-Authentifizierung mit JWT: Erfordert neue Backend-Endpunkte + Migration
- OAuth2/OIDC: Zu komplex für MVP-Anforderungen
- Kein Passwortschutz: Ungeschützte Landing-Page akzeptabel für interne Nutzung

**Trade-offs:**
- Frontend-Check ist umgehbar (akzeptabel für interne Tools)
- Später durch echte Backend-Authentifizierung ersetzbar (Migration-Path vorhanden)

**Migration-Path:**
- Phase 1: Frontend-Only-Check für MVP
- Phase 2: Backend-Endpunkt `POST /api/auth/login` hinzufügen
- Phase 3: JWT-basierte Session-Management implementieren

### Decision 3: Manual Session-ID Input with URL-Routing Fallback

**Rationale:**
- Primärer Use-Case: Kunde nutzt separates Gerät und erhält Session-ID verbal/per Text
- Manuelle Eingabe ist einfacher als URL-Sharing zwischen unterschiedlichen Geräten
- Input-Validierung (8 Zeichen, Uppercase) reduziert Eingabefehler
- URL-Routing (`/join/{id}`) bleibt als Alternative für QR-Code-Szenarien verfügbar

**Alternatives Considered:**
- Nur URL-Routing: Nicht praktikabel wenn Admin und Kunde unterschiedliche Geräte nutzen
- Hybrid-Ansatz: Beide Modi unterstützt (GEWÄHLT)

**Trade-offs:**
- Manuelle Eingabe erhöht Fehlerrisiko (mitigiert durch Inline-Validierung)
- UI-Komplexität leicht erhöht (zwei Eingabe-Modi)

**Implementation Details:**
```typescript
// Session-ID Input mit Validierung
const validateSessionId = (id: string): boolean => {
  return /^[A-Z0-9]{8}$/.test(id);
};

// Routing unterstützt beide Modi
<Route path="/customer" element={<CustomerPage mode="manual" />} />
<Route path="/join/:sessionId" element={<CustomerPage mode="url" />} />
```

### Decision 4: WebSocket-First mit HTTP-Polling-Fallback

**Rationale:**
- Backend implementiert WebSocket-Broadcast mit automatischem Fallback
- WebSocket bietet <100ms Latenz für Echtzeit-Updates
- Polling-Fallback für CORS-Probleme oder restriktive Firewalls
- Backend liefert `fallback_activated` Message mit Polling-Endpunkt

**Alternatives Considered:**
- Nur WebSocket: Funktioniert nicht bei restriktiven Netzwerken
- Nur HTTP Polling: Höhere Latenz und Server-Last
- Server-Sent Events (SSE): Nur unidirektional, nicht ausreichend für Bidirektionalität

**Trade-offs:**
- Polling erhöht Server-Last (akzeptabel durch adaptive Polling-Frequenz)
- Komplexere Client-Logik für Fallback-Handling (vertretbar für bessere Robustheit)

**Implementation Details:**
```typescript
// WebSocket-First-Ansatz mit Auto-Fallback
class WebSocketService {
  connect() {
    try {
      this.ws = new WebSocket(WS_URL);
      this.ws.onerror = () => this.activatePollingFallback();
    } catch (error) {
      this.activatePollingFallback();
    }
  }

  activatePollingFallback() {
    this.pollingInterval = setInterval(() => {
      fetch(`/api/websocket/poll/${this.pollingId}`)
        .then(res => res.json())
        .then(messages => this.handleMessages(messages));
    }, 2000); // 2 Sekunden für Fallback-Modus
  }
}
```

### Decision 5: Optimistic UI für Message-Bubbles

**Rationale:**
- Sofortige visuelle Rückmeldung verbessert User-Experience
- Backend-Processing dauert 2-5 Sekunden (ASR + Translation + TTS)
- Pulsing-Dots-Indikator zeigt aktiven Verarbeitungszustand
- WebSocket-Bestätigung ersetzt temporäre Bubble durch finale Nachricht

**Alternatives Considered:**
- Blocking UI bis Backend-Response: Schlechtere UX, Nutzer wartet ohne Feedback
- Polling statt WebSocket: Höhere Latenz, verzögerte Bestätigung

**Trade-offs:**
- Komplexität durch temporäre/finale Bubble-States (vertretbar durch React-State-Management)
- Fehlgeschlagene Requests erfordern Bubble-Removal (Retry-Mechanismus implementiert)

**Implementation Details:**
```typescript
// Optimistic Message Bubble Flow
const sendMessage = (content: string) => {
  const tempId = generateTempId();

  // 1. Sofortige Anzeige mit Pulsing-Indikator
  addMessageBubble({ id: tempId, content, status: 'sending' });

  // 2. Backend-Request
  api.sendMessage(sessionId, content)
    .catch(() => {
      // 3. Error-Handling: Bubble mit Retry-Button
      updateMessageBubble(tempId, { status: 'error', retry: true });
    });

  // 4. WebSocket-Bestätigung ersetzt temporäre Bubble
  websocket.on('receiver_message', (msg) => {
    updateMessageBubble(tempId, {
      status: 'delivered',
      translation: msg.translation,
      audioUrl: msg.audio_url
    });
  });
};
```

### Decision 6: Multi-Stage Docker Build (Builder + Nginx)

**Rationale:**
- Builder-Stage kompiliert TypeScript und baut optimierte Bundles
- Nginx-Stage serviert statische Files und proxied API-Requests
- Kleinere Final-Image-Size (Alpine-basiert, ~50MB)
- Nginx als etablierter Production-Server für SPAs

**Alternatives Considered:**
- Node.js als Production-Server: Größeres Image, unnötiger Overhead
- Vite Preview als Production-Server: Nicht für Production empfohlen
- CDN-basiertes Hosting: Erfordert separate Infrastruktur

**Trade-offs:**
- Zwei-Stage-Build erhöht Build-Zeit (akzeptabel, ca. 2-3 Minuten)
- Nginx-Konfiguration erforderlich für SPA-Routing (Standard-Setup)

**Dockerfile Structure:**
```dockerfile
# Stage 1: Builder
FROM node:18-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --silent
COPY . .
RUN npm run build

# Stage 2: Nginx Production
FROM nginx:stable-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 5173
CMD ["nginx", "-g", "daemon off;"]
```

### Decision 7: TailwindCSS für Styling

**Rationale:**
- Utility-First-Ansatz beschleunigt Entwicklung
- Gute Mobile-Responsive-Utilities (sm:, md:, lg:)
- Tree-Shaking entfernt ungenutztes CSS (kleines Bundle)
- Etablierte Design-Patterns für Message-Bubbles und Chat-UIs

**Alternatives Considered:**
- Material-UI: Schwerer, opinionated Design-System
- Styled-Components: Runtime-Overhead, größeres Bundle
- Plain CSS/SCSS: Mehr Boilerplate, langsamere Entwicklung

**Trade-offs:**
- Initial-Learning-Curve für Utility-Classes (schnell amortisiert)
- Längere HTML-Class-Strings (akzeptabel durch gute Lesbarkeit)

## Risks & Mitigation

### Risk 1: WebSocket-Verbindung durch Traefik nicht stabil

**Mitigation:**
- HTTP-Polling-Fallback bereits im Backend implementiert
- Traefik-Labels in docker-compose.yml testen: `traefik.http.services.api_gateway.loadbalancer.passhostheader=true`
- WebSocket-Connection-Test-Endpunkt nutzen: `GET /api/websocket/debug/connection-test`
- Fallback-Mode-Indikator im UI zeigen (transparente Kommunikation mit Nutzern)

### Risk 2: Audio-Recording funktioniert nicht auf iOS Safari

**Mitigation:**
- MediaRecorder-Polyfill für iOS implementieren (opus-recorder)
- Fallback auf Text-Eingabe prominent platzieren
- Feature-Detection vor Audio-Aufnahme: `if (!navigator.mediaDevices) { showTextOnlyMode(); }`
- Klare Fehlermeldungen bei Permission-Denial oder unsupported Browsers

### Risk 3: Docker-Build-Zeit zu lang für Entwicklungs-Iterationen

**Mitigation:**
- Development-Mode mit Volume-Mount statt Build: `docker-compose.dev.yml`
- Vite Hot-Module-Replacement für schnelle Feedback-Loops
- Multi-Stage-Build nur für Production-Builds
- Layer-Caching durch separates `npm ci` vor `COPY . .`

### Risk 4: Session-Aktivierung Race-Condition (Admin sieht Status nicht sofort)

**Mitigation:**
- WebSocket-Verbindung bereits bei Session-Erstellung etablieren
- Polling-Fallback alle 2 Sekunden bei `pending` Status
- Backend sendet WebSocket-Event bei Aktivierung: `{type: "session_activated"}`
- Optimistisches Status-Update im Frontend bei Kunden-Aktivierung

### Risk 5: Große Bundle-Size durch Dependencies

**Mitigation:**
- Code-Splitting für Route-basierte Chunks: `React.lazy(() => import('./AdminPage'))`
- Tree-Shaking durch Vite aktiviert (default)
- Dependency-Analyse mit `vite-bundle-visualizer`
- Lazy-Loading für QR-Code-Library (nur Admin braucht sie)

## Migration Plan

### Phase 1: MVP - Basic Functionality (Week 1-2)

**Scope:**
- Landing-Page mit optional Frontend-Passwortschutz
- Admin-Session-Erstellung mit QR-Code
- Kunden-Session-Aktivierung mit Sprachauswahl
- Basis-Kommunikations-Interface (Text-Eingabe, WebSocket-Integration)
- Docker-Build mit Nginx

**Acceptance Criteria:**
- Admin kann Session erstellen und URL teilen
- Kunde kann Session aktivieren und Sprache wählen
- Beide können Text-Nachrichten senden und empfangen
- WebSocket-Updates funktionieren in Echtzeit
- Deployment via docker-compose erfolgreich

### Phase 2: Enhanced UX (Week 3)

**Scope:**
- Audio-Aufnahme mit WebRTC
- Optimistic UI mit Pulsing-Bubbles
- Pipeline-Metadaten-Anzeige
- Responsive Design für Mobile
- Error-Handling und Retry-Mechanismus

**Acceptance Criteria:**
- Audio-Nachrichten funktionieren auf Desktop und Mobile
- Pulsing-Indikator zeigt Verarbeitungszustand
- Metadaten (Processing-Zeit, Sprachen) sind sichtbar
- UI funktioniert auf Smartphones ohne Scrolling-Probleme
- Fehlgeschlagene Requests können wiederholt werden

### Phase 3: Production-Ready (Week 4)

**Scope:**
- Polling-Fallback für WebSocket-Failures
- Message-History-Loading
- Session-Beendigung/-Wechsel
- Accessibility-Improvements (ARIA, Keyboard-Navigation)
- Testing (Unit, Integration, E2E)

**Acceptance Criteria:**
- Polling-Fallback aktiviert sich automatisch bei WebSocket-Problemen
- Message-History wird beim Session-Join geladen
- Session-Terminierung funktioniert bidirektional
- Screen-Reader können alle Funktionen nutzen
- Test-Coverage >70% für kritische Komponenten

### Phase 4: Polish & Optimization (Week 5)

**Scope:**
- Bundle-Size-Optimierung
- Service-Worker für Offline-Support (optional)
- Frontend-Monitoring (Sentry, LogRocket)
- User-Guide und Dokumentation
- Performance-Tuning

**Acceptance Criteria:**
- Bundle-Size <500KB (gzipped)
- Lighthouse-Score >90 für Performance
- Error-Tracking ist aktiv
- Dokumentation ist vollständig
- Load-Time <2 Sekunden auf 3G

## Rollback Strategy

### Scenario 1: Frontend-Deployment fehlschlägt

**Rollback-Steps:**
1. `docker compose down frontend` (neuer Service stoppen)
2. `docker compose up -d frontend-archive` (altes Frontend starten)
3. Traefik-Labels in docker-compose.yml umkehren (Archive → Main)
4. DNS-Cache-Clear (falls nötig)

### Scenario 2: WebSocket-Integration funktioniert nicht in Production

**Fallback:**
- Backend hat bereits Polling-Fallback implementiert
- Frontend zeigt Fallback-Mode-Indikator
- Keine Rollback erforderlich, nur reduzierte Performance

### Scenario 3: Audio-Recording verursacht Browser-Crashes

**Mitigation:**
- Feature-Flag für Audio-Modus in Environment-Variable: `ENABLE_AUDIO_INPUT=false`
- Nur Text-Modus aktivieren bis Bug gefixt ist
- Schnelles Re-Deployment mit aktualisiertem Dockerfile

## Open Questions

1. ~~**Passwortschutz:** Soll Frontend-Only-Check für MVP ausreichen oder sofort Backend-Auth implementieren?~~
   - ✅ **DECIDED:** Frontend-Only für MVP, Backend-Auth in Phase 2

2. ~~**Multi-Session-Support für Admin:** Soll Admin mehrere Sessions parallel verwalten können?~~
   - ✅ **DECIDED:** Single-Session für MVP, Multi-Session als Feature-Request für spätere Phase

3. ~~**Message-History:** Soll komplette Historie beim Session-Start geladen werden?~~
   - ✅ **DECIDED:** Ja, über `GET /api/session/{id}/messages` beim Component-Mount

4. ~~**Audio-Autoplay:** Soll übersetzte Audio automatisch abgespielt werden?~~
   - ✅ **DECIDED:** Ja, automatisch nach initialer User-Interaction (Browser-Policy)

5. ~~**Session-ID-Eingabe:** URL-Routing oder manuelles Input-Feld?~~
   - ✅ **DECIDED:** Manuelles Input primär, URL-Routing als Fallback für QR-Codes

6. **Language-Persistence:** Soll gewählte Sprache in localStorage gespeichert werden?
   - **Recommendation:** Nein für MVP (Session-basiert), optional für User-Convenience

7. **Error-Logging:** Soll Frontend-Errors zu Backend-Monitoring-Stack gesendet werden?
   - **Recommendation:** Ja, über Prometheus `/metrics` Endpoint oder Sentry

8. **Offline-Support:** Ist Service-Worker für Offline-First erforderlich?
   - **Recommendation:** Nein für MVP (Echtzeit-App benötigt Backend), optional später
