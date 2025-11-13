# Audio Recording Feature - Manuelle Test-Checkliste

## 📋 Übersicht

Diese Checkliste führt dich Schritt für Schritt durch die manuellen Browser-Tests des Audio-Recording-Features. Arbeite die Punkte systematisch ab und dokumentiere alle Ergebnisse.

**Deployment-URL**: `https://translate.smart-village.solutions`

---

## 🔍 Test-Vorbereitung

### Allgemeine Voraussetzungen
- [ ] **Mikrofon verfügbar**: Funktionierendes Mikrofon angeschlossen/eingebaut
- [ ] **HTTPS-Verbindung**: Bestätigt (für getUserMedia API erforderlich)
- [ ] **Browser-Console geöffnet**: F12 → Console & Network Tab
- [ ] **Test-Notizen vorbereitet**: Dokument für Ergebnisse bereit

### System-Check
- [ ] **Backend erreichbar**: `https://translate.smart-village.solutions` lädt
- [ ] **WebSocket-Verbindung**: Console zeigt "WebSocket connected"
- [ ] **Keine JavaScript-Fehler**: Console ist sauber (keine roten Fehler)

---

## 🧪 Test-Szenarien

### Test 1: Chrome (Desktop)

#### 1.1 Session erstellen
- [ ] Browser öffnen: Google Chrome (neueste Version)
- [ ] URL öffnen: `https://translate.smart-village.solutions`
- [ ] Admin-Ansicht: Session erstellen
  - [ ] Source Language: Deutsch (de)
  - [ ] Target Language: Englisch (en)
  - [ ] Session-Code notieren: `____________`
- [ ] Kunde-Ansicht (Incognito): Session beitreten mit Code

#### 1.2 Audio-Aufnahme (Kunde → Admin)
- [ ] **Klick auf Mikrofon-Icon** (Kunde-Ansicht)
- [ ] **Mikrofon-Berechtigung**: Browser fragt → "Erlauben" klicken
- [ ] **Recording-Animation**: Icon zeigt Recording-Status (rot/pulsierend)
- [ ] **Test-Sprache**: "Hallo, das ist ein Test." (5 Sekunden sprechen)
- [ ] **Stop Recording**: Erneut auf Mikrofon-Icon klicken

#### 1.3 Verarbeitung beobachten
- [ ] **Optimistic Update**: Nachricht erscheint sofort mit "Processing..." Status
- [ ] **Console-Logs**:
  - [ ] "Converting browser audio to WAV..." erscheint
  - [ ] "Audio conversion successful: ... bytes" erscheint
  - [ ] "Uploading WAV file..." erscheint
- [ ] **Network-Tab**:
  - [ ] POST-Request zu `/api/session/{sessionId}/message`
  - [ ] Content-Type: `multipart/form-data`
  - [ ] Form-Data enthält: `file`, `source_lang=de`, `target_lang=en`, `client_type=customer`
  - [ ] Response 200 OK

#### 1.4 Ergebnis überprüfen
- [ ] **Admin-Ansicht**: Nachricht empfangen
  - [ ] **Originaltext** (Deutsch): `________________________`
  - [ ] **Übersetzung** (Englisch): `________________________`
- [ ] **TTS-Audio**: Audio wird abgespielt (Admin-Ansicht)
- [ ] **WebSocket-Broadcast**: Beide Clients zeigen finale Nachricht

#### 1.5 Performance messen
- [ ] **Audio-Konvertierung**: `______` ms (< 500ms? ✅/❌)
- [ ] **ASR-Verarbeitung**: `______` ms (< 200ms? ✅/❌)
- [ ] **Translation**: `______` ms (< 100ms? ✅/❌)

#### 1.6 Audio-Aufnahme (Admin → Kunde)
- [ ] **Klick auf Mikrofon-Icon** (Admin-Ansicht)
- [ ] **Test-Sprache**: "This is a response message." (5 Sekunden)
- [ ] **Stop Recording**: Mikrofon-Icon erneut klicken
- [ ] **Kunde-Ansicht**: Nachricht empfangen mit Übersetzung (Englisch → Deutsch)

---

### Test 2: Firefox (Desktop)

#### 2.1 Session erstellen
- [ ] Browser öffnen: Mozilla Firefox (neueste Version)
- [ ] URL öffnen: `https://translate.smart-village.solutions`
- [ ] Admin-Ansicht: Session erstellen (de → en)
- [ ] Kunde-Ansicht (Private Window): Session beitreten

#### 2.2 Audio-Aufnahme (Kunde → Admin)
- [ ] Mikrofon-Icon klicken → Berechtigung erlauben
- [ ] Recording-Animation: ✅/❌
- [ ] Test-Sprache: "Guten Tag, dies ist ein Firefox-Test."
- [ ] Stop Recording

#### 2.3 Verarbeitung und Ergebnis
- [ ] **Console**: "Converting OGG/Opus to WAV..." erscheint ✅/❌
- [ ] **Network**: POST-Request erfolgreich ✅/❌
- [ ] **Admin-Ansicht**: Nachricht empfangen ✅/❌
  - [ ] Originaltext: `________________________`
  - [ ] Übersetzung: `________________________`
- [ ] **TTS-Audio**: Abspielung erfolgreich ✅/❌

#### 2.4 Performance
- [ ] Audio-Konvertierung: `______` ms
- [ ] Gesamt-Pipeline: `______` ms

---

### Test 3: Safari (Desktop/iOS)

#### 3.1 Session erstellen
- [ ] Browser öffnen: Safari (neueste Version, macOS/iOS)
- [ ] URL öffnen: `https://translate.smart-village.solutions`
- [ ] Admin-Ansicht: Session erstellen (de → en)
- [ ] Kunde-Ansicht (Private Browsing): Session beitreten

#### 3.2 Audio-Aufnahme (Kunde → Admin)
- [ ] Mikrofon-Icon klicken → Berechtigung erlauben
- [ ] Recording-Animation: ✅/❌
- [ ] Test-Sprache: "Hallo aus Safari."
- [ ] Stop Recording

#### 3.3 Verarbeitung und Ergebnis
- [ ] **Console**: "Converting MP4/AAC to WAV..." erscheint ✅/❌
- [ ] **Network**: POST-Request erfolgreich ✅/❌
- [ ] **Admin-Ansicht**: Nachricht empfangen ✅/❌
  - [ ] Originaltext: `________________________`
  - [ ] Übersetzung: `________________________`
- [ ] **TTS-Audio**: Abspielung erfolgreich ✅/❌

#### 3.4 Safari-Spezifische Checks
- [ ] **iOS-Mikrofon**: Mikrofon-Zugriff funktioniert auf iPhone/iPad ✅/❌
- [ ] **iOS-Audio-Wiedergabe**: TTS-Audio spielt auf iOS ✅/❌

---

### Test 4: Edge (Desktop)

#### 4.1 Session erstellen
- [ ] Browser öffnen: Microsoft Edge (neueste Version)
- [ ] URL öffnen: `https://translate.smart-village.solutions`
- [ ] Admin-Ansicht: Session erstellen (de → en)
- [ ] Kunde-Ansicht (InPrivate): Session beitreten

#### 4.2 Audio-Aufnahme und Ergebnis
- [ ] Mikrofon-Icon klicken → Berechtigung erlauben ✅/❌
- [ ] Test-Sprache: "Edge-Browser-Test."
- [ ] Stop Recording ✅/❌
- [ ] **Console**: "Converting WebM/Opus to WAV..." ✅/❌
- [ ] **Network**: POST-Request erfolgreich ✅/❌
- [ ] **Admin-Ansicht**: Nachricht empfangen ✅/❌

---

## 🚨 Fehlerszenarien testen

### Fehler 1: Mikrofon-Berechtigung verweigert

#### Test-Schritte
- [ ] Browser: Chrome
- [ ] Session erstellen und beitreten
- [ ] Mikrofon-Icon klicken
- [ ] **Berechtigung VERWEIGERN** im Browser-Dialog

#### Erwartetes Verhalten
- [ ] **Fehlermeldung erscheint**: "Mikrofonzugriff erforderlich. Bitte erlaube den Zugriff in deinen Browser-Einstellungen."
- [ ] **Mikrofon-Icon**: Bleibt inaktiv (kein Recording)
- [ ] **Console**: Error-Log zeigt "Permission denied" ✅/❌

---

### Fehler 2: Netzwerkfehler simulieren

#### Test-Schritte
- [ ] Browser: Chrome
- [ ] Session erstellen und beitreten
- [ ] **Network Tab**: Throttling auf "Offline" setzen
- [ ] Mikrofon-Icon klicken → Audio aufnehmen
- [ ] Stop Recording

#### Erwartetes Verhalten
- [ ] **Fehlermeldung erscheint**: "Upload fehlgeschlagen. Bitte überprüfe deine Internetverbindung."
- [ ] **Console**: Error-Log zeigt Network-Fehler ✅/❌
- [ ] **Nachricht**: Bleibt im "Failed" Status ✅/❌

---

### Fehler 3: Leere Audio-Aufnahme

#### Test-Schritte
- [ ] Browser: Chrome
- [ ] Session erstellen und beitreten
- [ ] Mikrofon-Icon klicken (NICHT sprechen)
- [ ] Sofort Stop Recording (< 1 Sekunde)

#### Erwartetes Verhalten
- [ ] **Warnung erscheint**: "Audio zu kurz. Bitte sprich mindestens 1 Sekunde." (oder ähnlich)
- [ ] **Console**: Warnung über leere Audio-Datei ✅/❌

---

### Fehler 4: Keine Sprache erkannt (ASR-Fehler)

#### Test-Schritte
- [ ] Browser: Chrome
- [ ] Session erstellen und beitreten
- [ ] Mikrofon-Icon klicken
- [ ] **Unverständliche Geräusche** machen (Klopfen, Rauschen)
- [ ] Stop Recording

#### Erwartetes Verhalten
- [ ] **Fehlermeldung vom Backend**: "ASR konnte keine Sprache erkennen. Bitte spreche deutlicher."
- [ ] **Console**: Error-Response von Backend ✅/❌

---

## 📊 Test-Matrix (Zusammenfassung)

| Browser | Recording | Konvertierung | Upload | ASR | Translation | TTS | Status |
|---------|-----------|---------------|--------|-----|-------------|-----|--------|
| Chrome  | ☐         | ☐             | ☐      | ☐   | ☐           | ☐   | ☐ PASS / ☐ FAIL |
| Firefox | ☐         | ☐             | ☐      | ☐   | ☐           | ☐   | ☐ PASS / ☐ FAIL |
| Safari  | ☐         | ☐             | ☐      | ☐   | ☐           | ☐   | ☐ PASS / ☐ FAIL |
| Edge    | ☐         | ☐             | ☐      | ☐   | ☐           | ☐   | ☐ PASS / ☐ FAIL |

---

## 🐛 Bug-Report-Template

Falls Probleme auftreten, dokumentiere sie mit folgendem Template:

```
### Bug #X: [Kurze Beschreibung]

**Browser**: [Chrome/Firefox/Safari/Edge] Version [X.X.X]
**Betriebssystem**: [Windows/macOS/Linux/iOS/Android] Version [X.X]
**Session-Code**: [ABC123]

**Schritte zum Reproduzieren**:
1. [Schritt 1]
2. [Schritt 2]
3. [Schritt 3]

**Erwartetes Verhalten**:
[Was sollte passieren]

**Tatsächliches Verhalten**:
[Was ist passiert]

**Console-Logs**:
```
[Relevante Console-Logs hier einfügen]
```

**Network-Tab**:
- Request-URL: [...]
- Status-Code: [...]
- Response-Body: [...]

**Screenshots**:
[Screenshots anhängen, falls hilfreich]
```

---

## ✅ Test-Abschluss

### Finale Checkliste
- [ ] Alle 4 Browser getestet (Chrome, Firefox, Safari, Edge)
- [ ] Alle Fehlerszenarien durchgespielt (4 Tests)
- [ ] Test-Matrix ausgefüllt
- [ ] Bugs dokumentiert (falls vorhanden)
- [ ] Performance-Metriken notiert
- [ ] Test-Ergebnisse an Team kommuniziert

### Test-Status
- **Datum**: `____________`
- **Tester**: `____________`
- **Gesamt-Bewertung**: ☐ PASS / ☐ FAIL / ☐ NEEDS REVIEW

### Nächste Schritte
- [ ] Test-Ergebnisse in Confluence/Jira dokumentieren
- [ ] Gefundene Bugs als Issues anlegen
- [ ] Performance-Optimierungen priorisieren (falls nötig)
- [ ] Stakeholder informieren (Product Owner, Entwicklungsteam)

---

## 📚 Hilfreiche Ressourcen

- **Backend-Logs**: SSH in Server → `docker logs ssf-backend`
- **Dokumentation**: `/docs/AUDIO_RECORDING_BROWSER_TEST.md`
- **Test-Strategie**: `/docs/AUDIO_RECORDING_TEST_SUMMARY.md`
- **Rollback-Plan**: `/docs/AUDIO_RECORDING_ROLLBACK_STRATEGY.md`
