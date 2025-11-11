# Frontend Smoke Tests

## Deployment verifiziert am: 10. November 2025

### ✅ Basis-Tests (automatisch)

```bash
# 1. Frontend erreichbar
curl -I https://translate.smart-village.solutions
# Erwartung: HTTP/2 200

# 2. Health Check
curl https://translate.smart-village.solutions/health
# Erwartung: "healthy"

# 3. Backend API erreichbar
curl -s https://ssf.smart-village.solutions/api/languages/supported | jq '.languages | keys'
# Erwartung: ["ar", "de", "en", "tr", ...]

# 4. Container Status
docker compose ps frontend
# Erwartung: Up X seconds (healthy)

# 5. Logs überwachen
docker compose logs -f frontend | grep -E "GET|POST|ERROR"
```

---

## 🧪 Manuelle Smoke Tests

### Test 1: Landing Page & Passwort
1. ✅ Öffne: https://translate.smart-village.solutions
2. ✅ Seite lädt korrekt (kein CORS-Fehler in Console)
3. ✅ Passwort eingeben: `ssf2025kassel`
4. ✅ Buttons sichtbar: "Intern (Verwaltung)" und "Kunde"
5. ✅ Falsches Passwort zeigt Fehler

**Erwartung**: Passwort-Schutz funktioniert, Navigation möglich

---

### Test 2: Admin Session Flow
1. ✅ Klick auf "Intern (Verwaltung)"
2. ✅ Button "Neue Session erstellen" anklicken
3. ✅ Session-ID erscheint (8 Zeichen, z.B. `EEF1B592`)
4. ✅ Status zeigt "Warte auf Kunde..." (gelber Badge)
5. ⏳ WebSocket-Verbindung grün (ConnectionStatusIndicator)

**Backend-Logs prüfen**:
```bash
docker compose logs api_gateway | grep "Session erstellt"
# Erwartung: ✅ Neue Admin-Session erstellt: [SESSION_ID]
```

**Erwartung**: Session-Erstellung funktioniert, Status korrekt

---

### Test 3: Customer Join Flow
**Voraussetzung**: Admin-Session aus Test 2 aktiv

1. ✅ Neuer Browser-Tab (oder Inkognito-Modus)
2. ✅ https://translate.smart-village.solutions öffnen
3. ✅ Passwort: `ssf2025kassel`
4. ✅ Klick auf "Kunde"
5. ✅ Session-ID eingeben (aus Test 2, z.B. `EEF1B592`)
6. ✅ Sprache auswählen (z.B. "Arabisch")
7. ✅ Button "Session beitreten" klicken
8. ⏳ Customer-Interface lädt
9. ⏳ WebSocket-Verbindung grün

**Im Admin-Tab prüfen**:
- Status wechselt zu "Aktiv" (grüner Badge)
- WebSocket-Notification: "Customer joined"

**Backend-Logs prüfen**:
```bash
docker compose logs api_gateway | grep -i "activate\|customer"
```

**Erwartung**: Customer kann Session beitreten, Admin wird benachrichtigt

---

### Test 4: Text-Nachrichten
**Voraussetzung**: Admin und Customer verbunden (Test 2 + 3)

**Admin sendet Text**:
1. ⏳ Text eingeben: "Hallo, willkommen!"
2. ⏳ Send-Button klicken
3. ⏳ Message erscheint als "Sender" (blaue Bubble)
4. ⏳ Pulsing dots während Verarbeitung
5. ⏳ ASR-Text wird angezeigt (gleicher Text)
6. ⏳ Pipeline-Metadata anklickbar

**Customer empfängt Translation**:
1. ⏳ Message erscheint als "Receiver" (graue Bubble)
2. ⏳ Übersetzter Text auf Arabisch
3. ⏳ Audio-Player erscheint
4. ⏳ Audio spielt automatisch ab (nach User-Geste)

**Backend-Logs prüfen**:
```bash
docker compose logs api_gateway | grep -E "POST.*message|pipeline"
```

**Erwartung**: Text wird übersetzt, TTS generiert, beide Seiten sehen Messages

---

### Test 5: Audio-Nachrichten (HTTPS erforderlich!)
**Voraussetzung**: Admin und Customer verbunden

**Customer sendet Audio**:
1. ⏳ Toggle auf Mikrofon-Icon klicken
2. ⏳ Browser fragt nach Mikrofon-Berechtigung → Erlauben
3. ⏳ Record-Button klicken (Icon pulsiert rot)
4. ⏳ 3-5 Sekunden sprechen (Arabisch)
5. ⏳ Stop-Button klicken
6. ⏳ Message wird gesendet (Optimistic UI)
7. ⏳ ASR-Text erscheint (transkribierter arabischer Text)

**Admin empfängt Translation**:
1. ⏳ Message erscheint mit deutschem Text
2. ⏳ Audio-Player mit deutscher TTS
3. ⏳ Audio spielt automatisch ab

**Fehlerbehebung**:
- Mikrofon-Zugriff verweigert? → Nur über HTTPS möglich
- Kein Audio? → Browser-Console prüfen (F12)
- Audio-Format-Fehler? → MediaRecorder API Browser-Support prüfen

**Erwartung**: Audio-Aufnahme funktioniert, ASR + Translation + TTS Pipeline läuft

---

### Test 6: WebSocket Reconnect
**Voraussetzung**: Aktive Session mit Messages

1. ⏳ Backend kurz stoppen:
   ```bash
   docker compose stop api_gateway
   ```
2. ⏳ Connection Status wird gelb/rot
3. ⏳ Frontend zeigt "Verbindung verloren"
4. ⏳ Backend neu starten:
   ```bash
   docker compose start api_gateway
   ```
5. ⏳ Connection Status wird gelb (reconnecting)
6. ⏳ Nach 1-2 Sekunden grün (connected)
7. ⏳ Message-Historie bleibt erhalten
8. ⏳ Neue Messages funktionieren

**Erwartung**: Auto-Reconnect funktioniert, keine Message-Verluste

---

### Test 7: Session Termination
**Voraussetzung**: Aktive Session

**Admin beendet Session**:
1. ⏳ Button "Session beenden" klicken
2. ⏳ Bestätigungs-Dialog erscheint
3. ⏳ "Ja, beenden" klicken
4. ⏳ Admin kehrt zum Erstellungs-Screen zurück

**Customer-Side**:
1. ⏳ WebSocket-Event empfangen
2. ⏳ Toast-Notification: "Session beendet"
3. ⏳ Redirect zur Landing Page

**Backend-Logs**:
```bash
docker compose logs api_gateway | grep "beendet"
# Erwartung: 🔚 Session [ID] beendet
```

**Erwartung**: Session-Beendigung benachrichtigt beide Seiten

---

## 🔍 Monitoring-Checkliste

### Browser-Console (F12)
- ✅ Keine CORS-Fehler
- ✅ Keine JavaScript-Fehler
- ✅ WebSocket-Verbindung erfolgreich (101 Switching Protocols)
- ✅ API-Calls erfolgreich (200/201 Status)

### Backend-Logs
```bash
# Alle Requests anzeigen
docker compose logs -f api_gateway

# WebSocket-Verbindungen
docker compose logs api_gateway | grep -i "websocket\|ws"

# Session-Events
docker compose logs api_gateway | grep -i "session"

# Pipeline-Processing
docker compose logs api_gateway | grep -i "pipeline"
```

### Frontend-Logs
```bash
# Nginx Access Logs
docker compose logs -f frontend

# Fehler suchen
docker compose logs frontend | grep -i "error"
```

---

## 🐛 Bekannte Probleme & Lösungen

### Problem: WebSocket verbindet nicht
**Symptome**: Roter Connection Status, Console: "WebSocket failed"
**Lösung**:
1. Backend-Logs prüfen: `docker compose logs api_gateway | tail -50`
2. Traefik-Routing prüfen: `curl -I https://ssf.smart-village.solutions/health`
3. WebSocket-Endpoint manuell testen: `wscat -c wss://ssf.smart-village.solutions/ws/TEST1234/admin`

### Problem: Mikrofon-Zugriff verweigert
**Symptome**: "Permission denied" bei Audio-Aufnahme
**Lösung**:
- Browser-Einstellungen: Site-Permissions → Mikrofon erlauben
- Nur über HTTPS möglich (HTTP blockiert Media Capture API)
- Firewall/Antivirus prüfen

### Problem: Audio spielt nicht ab
**Symptome**: Audio-Player erscheint, aber kein Sound
**Lösung**:
1. Browser-Console prüfen (AutoPlay-Policy)
2. Erste User-Geste erforderlich (Button-Click)
3. Browser-Volume prüfen
4. Audio-Format: Prüfe ob Browser WAV/MP3 unterstützt

### Problem: Session-ID nicht gefunden (404)
**Symptome**: "Session not found" beim Beitreten
**Lösung**:
1. Session-ID korrekt eingegeben? (8 Zeichen, Großbuchstaben)
2. Session noch aktiv? Timeout = 15 Minuten
3. Backend-Logs: `docker compose logs api_gateway | grep [SESSION_ID]`

---

## ✅ Erfolgs-Kriterien

**Deployment ist erfolgreich, wenn**:
- [x] Frontend erreichbar unter https://translate.smart-village.solutions
- [x] SSL/TLS funktioniert (Let's Encrypt)
- [x] Landing Page lädt ohne Fehler
- [ ] Passwort-Schutz funktioniert
- [ ] Admin kann Session erstellen
- [ ] Customer kann Session beitreten
- [ ] Text-Nachrichten werden übersetzt
- [ ] Audio-Nachrichten funktionieren (ASR + TTS)
- [ ] WebSocket-Verbindung stabil
- [ ] Auto-Reconnect funktioniert
- [ ] Session-Beendigung benachrichtigt beide Seiten
- [ ] Keine kritischen Fehler in Logs

**Status**: 🟡 Deployment erfolgreich, manuelle Tests ausstehend
