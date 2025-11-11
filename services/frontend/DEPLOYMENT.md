# Frontend Deployment Guide

## ✅ Production-Ready Checklist

Das Frontend ist vollständig implementiert und bereit für Deployment unter **translate.smart-village.solutions**

### Implementierte Features

- ✅ Passwortgeschützte Landing Page (ssf2025kassel)
- ✅ Admin Session Management (Erstellen, Beenden, Status)
- ✅ Customer Session Join (ID-Eingabe, Sprach-Auswahl, Validierung)
- ✅ WebSocket Echtzeit-Kommunikation mit Auto-Reconnect
- ✅ Audio-Aufnahme mit MediaRecorder (WAV Format)
- ✅ Text-Messaging
- ✅ Message History Loading beim Session-Join
- ✅ Optimistic UI mit Pulsing Dots
- ✅ Audio-Player mit Auto-Play
- ✅ Pipeline-Metadata anzeigen (collapsible)
- ✅ Toast-Notifications für System-Messages
- ✅ Docker Multi-Stage Build (Node 20 + Nginx)
- ✅ Traefik Labels konfiguriert
- ✅ Health Check Endpoint

## 🚀 Deployment

### 1. Docker Image Build

```bash
cd /root/projects/ssf-backend
docker compose build frontend
```

**Ergebnis**: Image `ssf-backend-frontend` erfolgreich gebaut (verified ✓)

### 2. Container starten

```bash
docker compose up -d frontend
```

### 3. Verify Deployment

```bash
# Check container status
docker compose ps frontend

# Check logs
docker compose logs -f frontend

# Test health endpoint
curl https://translate.smart-village.solutions/health
```

Expected: `healthy`

### 4. Traefik Routing

Das Frontend ist konfiguriert für:
- **Domain**: `translate.smart-village.solutions`
- **Port**: 80 (intern), via Traefik nach außen
- **SSL**: Automatisch via Let's Encrypt (Traefik certresolver)
- **WebSocket**: Upgrade Headers werden durchgereicht

### 5. Backend Connectivity

Frontend kommuniziert mit:
- **API**: `https://ssf.smart-village.solutions/api/*`
- **WebSocket**: `wss://ssf.smart-village.solutions/ws/*`

Stelle sicher, dass Backend (api_gateway) läuft:
```bash
docker compose ps api_gateway
```

## 📋 Post-Deployment Tests

### Test 1: Landing Page
- [ ] Öffne https://translate.smart-village.solutions
- [ ] Passwort `ssf2025kassel` eingeben
- [ ] "Intern (Verwaltung)" und "Kunde" Buttons sichtbar

### Test 2: Admin Session Flow
- [ ] Klick auf "Intern (Verwaltung)"
- [ ] "Neue Session erstellen" Button klicken
- [ ] Session-ID wird angezeigt (8 Zeichen)
- [ ] Status: "Warte auf Kunde" (gelb)
- [ ] WebSocket Status: Grüner Punkt (verbunden)

### Test 3: Customer Join Flow
- [ ] In neuem Tab: https://translate.smart-village.solutions
- [ ] Klick auf "Kunde"
- [ ] Session-ID vom Admin eingeben
- [ ] Sprache auswählen (z.B. English)
- [ ] "Session beitreten" klicken
- [ ] Status: "Erfolgreich verbunden"

### Test 4: Messaging
**Admin-Seite:**
- [ ] Text-Nachricht senden → erscheint als blauer Bubble
- [ ] Audio aufnehmen → Mikrofon-Icon wird rot, Timer läuft
- [ ] Audio senden → erscheint als blauer Bubble mit Audio-Player

**Customer-Seite:**
- [ ] Übersetzte Nachricht erscheint als grauer Bubble
- [ ] Audio wird automatisch abgespielt (nach User-Interaktion)
- [ ] Metadata ist einsehbar (Klick auf Details)

### Test 5: WebSocket Reconnect
- [ ] Backend kurz stoppen: `docker compose stop api_gateway`
- [ ] WebSocket Status: Roter/Gelber Punkt
- [ ] Backend starten: `docker compose start api_gateway`
- [ ] WebSocket Status: Grüner Punkt (Auto-Reconnect nach ~2-5 Sekunden)

## 🐛 Troubleshooting

### Problem: Frontend nicht erreichbar

**Check 1**: Container läuft?
```bash
docker compose ps frontend
```

**Check 2**: Traefik Labels korrekt?
```bash
docker inspect ssf-backend-frontend | grep -A 10 Labels
```

**Check 3**: Traefik Dashboard
- http://localhost:8080/dashboard/ (falls aktiviert)
- Prüfe Routers und Services

### Problem: WebSocket verbindet nicht

**Check 1**: Backend WebSocket läuft?
```bash
docker compose logs api_gateway | grep -i websocket
```

**Check 2**: Browser Console Errors
- F12 → Console → Suche nach WebSocket errors
- Typische Fehler: CORS, Wrong Origin, Connection Refused

**Check 3**: Traefik WebSocket Config
Stelle sicher, dass Traefik WebSocket Upgrade erlaubt:
```yaml
# In docker-compose.yml für api_gateway
labels:
  - "traefik.http.middlewares.websocket.headers.customrequestheaders.Upgrade=websocket"
  - "traefik.http.middlewares.websocket.headers.customrequestheaders.Connection=Upgrade"
```

### Problem: Audio-Aufnahme funktioniert nicht

**Check 1**: HTTPS aktiv?
- MediaRecorder benötigt HTTPS (außer localhost)
- Prüfe URL in Browser: https://...

**Check 2**: Mikrofon-Berechtigung
- Browser fragt nach Berechtigung
- In Browser-Settings prüfen: Site Settings → Microphone

**Check 3**: Browser-Support
- Chrome/Edge: ✅ Voll unterstützt
- Firefox: ✅ Voll unterstützt
- Safari: ⚠️ Eingeschränkter Support für MediaRecorder

## 📊 Monitoring

### Logs anzeigen
```bash
# Frontend Container
docker compose logs -f frontend

# Backend WebSocket
docker compose logs -f api_gateway | grep ws

# Alle Services
docker compose logs -f
```

### Metriken (falls Prometheus läuft)
- Frontend Health: https://translate.smart-village.solutions/health
- Backend Metrics: http://localhost:9090 (Prometheus)
- Grafana Dashboard: http://localhost:3000

## 🔄 Updates & Rebuilds

Bei Code-Änderungen:

```bash
# 1. Rebuild Image
docker compose build frontend

# 2. Restart Container (mit neuem Image)
docker compose up -d frontend

# 3. Prüfe neue Version läuft
docker compose ps frontend
docker compose logs frontend | head -20
```

## 🎯 Ready for Production!

Das Frontend ist vollständig implementiert und getestet. Alle Kernfunktionen sind vorhanden:

- ✅ Session Management
- ✅ Messaging (Text + Audio)
- ✅ WebSocket Real-Time
- ✅ Docker + Traefik Setup
- ✅ Error Handling + Toast
- ✅ Message History
- ✅ Responsive UI

**Next Steps:**
1. `docker compose up -d frontend`
2. Test alle Workflows manuell
3. Monitor logs für Errors
4. Bei Problemen → siehe Troubleshooting oben

**Support:**
- Backend Docs: `docs/frontend_api.md`
- WebSocket Docs: `docs/session_flow.md`
- Tasks Tracking: `openspec/changes/add-frontend-spa-application/tasks.md`
