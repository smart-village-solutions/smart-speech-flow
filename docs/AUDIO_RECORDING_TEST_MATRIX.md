# Browser Test Matrix - Audio Recording Feature

## Test-Übersicht
| Eigenschaft | Wert |
|-------------|------|
| Feature | Audio Recording mit WAV-Konvertierung |
| Test-URL | https://translate.smart-village.solutions |
| Test-Datum | [YYYY-MM-DD] |
| Tester | [Name] |
| Backend-Version | [Commit-Hash] |
| Frontend-Version | [Commit-Hash] |

---

## Browser-Kompatibilitäts-Matrix

### Funktionale Tests

| Test-ID | Test-Beschreibung | Chrome | Firefox | Safari | Edge | Notizen |
|---------|-------------------|--------|---------|--------|------|---------|
| BT-01 | Session erstellen | ☐ | ☐ | ☐ | ☐ | Source: de, Target: en |
| BT-02 | Mikrofon-Berechtigung anfordern | ☐ | ☐ | ☐ | ☐ | Dialog erscheint |
| BT-03 | Recording starten | ☐ | ☐ | ☐ | ☐ | Icon-Animation |
| BT-04 | Recording stoppen | ☐ | ☐ | ☐ | ☐ | Icon zurück zu normal |
| BT-05 | Audio-Konvertierung (Browser → WAV) | ☐ | ☐ | ☐ | ☐ | Console-Log prüfen |
| BT-06 | WAV-Upload (FormData POST) | ☐ | ☐ | ☐ | ☐ | Network-Tab prüfen |
| BT-07 | ASR-Verarbeitung | ☐ | ☐ | ☐ | ☐ | Deutscher Text erkannt |
| BT-08 | Translation | ☐ | ☐ | ☐ | ☐ | Englische Übersetzung |
| BT-09 | TTS-Audio-Wiedergabe | ☐ | ☐ | ☐ | ☐ | Audio hörbar |
| BT-10 | WebSocket-Broadcast (Admin → Kunde) | ☐ | ☐ | ☐ | ☐ | Beide Clients aktualisiert |
| BT-11 | Optimistic UI-Update | ☐ | ☐ | ☐ | ☐ | Nachricht sofort sichtbar |
| BT-12 | Error-Handling (Mikrofon verweigert) | ☐ | ☐ | ☐ | ☐ | Fehlermeldung angezeigt |
| BT-13 | Error-Handling (Netzwerkfehler) | ☐ | ☐ | ☐ | ☐ | Retry-Option angeboten |
| BT-14 | Audio-Format-Erkennung | ☐ | ☐ | ☐ | ☐ | Korrekt für jeden Browser |

**Legende**: ✅ = PASS, ❌ = FAIL, ⚠️ = PARTIAL, ⏸️ = SKIPPED, ☐ = NOT TESTED

---

## Performance-Metriken

### Audio-Konvertierung (Browser → WAV)

| Browser | Test 1 (5s Audio) | Test 2 (10s Audio) | Test 3 (15s Audio) | Durchschnitt | Ziel (<500ms) |
|---------|-------------------|--------------------|--------------------|--------------|---------------|
| Chrome  | ___ ms | ___ ms | ___ ms | ___ ms | ☐ ✅ / ☐ ❌ |
| Firefox | ___ ms | ___ ms | ___ ms | ___ ms | ☐ ✅ / ☐ ❌ |
| Safari  | ___ ms | ___ ms | ___ ms | ___ ms | ☐ ✅ / ☐ ❌ |
| Edge    | ___ ms | ___ ms | ___ ms | ___ ms | ☐ ✅ / ☐ ❌ |

### Upload-Zeit (WAV → Backend)

| Browser | Audio-Größe (bytes) | Upload-Zeit (ms) | Bandbreite | Status |
|---------|---------------------|------------------|------------|--------|
| Chrome  | _______ | ___ ms | _____ kbps | ☐ |
| Firefox | _______ | ___ ms | _____ kbps | ☐ |
| Safari  | _______ | ___ ms | _____ kbps | ☐ |
| Edge    | _______ | ___ ms | _____ kbps | ☐ |

### End-to-End-Pipeline (Recording → TTS-Audio)

| Browser | Recording (s) | Konvertierung (ms) | Upload (ms) | ASR (ms) | Translation (ms) | TTS (ms) | Gesamt (ms) | Ziel (<3000ms) |
|---------|---------------|-----------------------|-------------|----------|------------------|----------|-------------|----------------|
| Chrome  | 5s | ___ | ___ | ___ | ___ | ___ | ___ | ☐ ✅ / ☐ ❌ |
| Firefox | 5s | ___ | ___ | ___ | ___ | ___ | ___ | ☐ ✅ / ☐ ❌ |
| Safari  | 5s | ___ | ___ | ___ | ___ | ___ | ___ | ☐ ✅ / ☐ ❌ |
| Edge    | 5s | ___ | ___ | ___ | ___ | ___ | ___ | ☐ ✅ / ☐ ❌ |

---

## Audio-Format-Details

### Browser-spezifische Formate

| Browser | MediaRecorder Output | Sample Rate | Channels | Codec | Konvertierung-Ziel |
|---------|---------------------|-------------|----------|-------|--------------------|
| Chrome  | WebM/Opus | 48000 Hz | Stereo | Opus | 16000 Hz, Mono, PCM 16-bit |
| Firefox | OGG/Opus | 48000 Hz | Stereo | Opus | 16000 Hz, Mono, PCM 16-bit |
| Safari  | MP4/AAC | 44100 Hz | Mono | AAC | 16000 Hz, Mono, PCM 16-bit |
| Edge    | WebM/Opus | 48000 Hz | Stereo | Opus | 16000 Hz, Mono, PCM 16-bit |

### WAV-Format-Validierung

| Browser | RIFF-Header ✅ | WAVE-Header ✅ | fmt-Chunk ✅ | data-Chunk ✅ | Sample-Rate (16kHz) ✅ | Channels (Mono) ✅ | Bits-per-Sample (16) ✅ |
|---------|---------------|---------------|-------------|-------------|------------------------|-------------------|------------------------|
| Chrome  | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |
| Firefox | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |
| Safari  | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |
| Edge    | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |

---

## Fehlerszenarien-Matrix

| Fehler-ID | Fehler-Beschreibung | Chrome | Firefox | Safari | Edge | Notizen |
|-----------|---------------------|--------|---------|--------|------|---------|
| ERR-01 | Mikrofon-Berechtigung verweigert | ☐ | ☐ | ☐ | ☐ | Fehlermeldung angezeigt? |
| ERR-02 | Netzwerkfehler (Offline) | ☐ | ☐ | ☐ | ☐ | Retry-Option? |
| ERR-03 | Leere Audio-Aufnahme (<1s) | ☐ | ☐ | ☐ | ☐ | Warnung angezeigt? |
| ERR-04 | Keine Sprache erkannt (ASR-Fehler) | ☐ | ☐ | ☐ | ☐ | Backend-Fehlermeldung? |
| ERR-05 | WebSocket-Verbindung verloren | ☐ | ☐ | ☐ | ☐ | Reconnect funktioniert? |
| ERR-06 | Ungültige Session-ID | ☐ | ☐ | ☐ | ☐ | 404-Fehler abgefangen? |
| ERR-07 | Backend-Timeout (>30s) | ☐ | ☐ | ☐ | ☐ | Timeout-Meldung? |
| ERR-08 | Mikrofon-Zugriff während Recording verloren | ☐ | ☐ | ☐ | ☐ | Graceful Degradation? |

**Legende**: ✅ = HANDLED CORRECTLY, ❌ = NOT HANDLED, ⚠️ = PARTIAL, ☐ = NOT TESTED

---

## User Experience (UX) Bewertung

| Kriterium | Chrome | Firefox | Safari | Edge | Notizen |
|-----------|--------|---------|--------|------|---------|
| Mikrofon-Icon klar erkennbar | ☐ 1-5 | ☐ 1-5 | ☐ 1-5 | ☐ 1-5 | 1=schlecht, 5=exzellent |
| Recording-Animation intuitiv | ☐ 1-5 | ☐ 1-5 | ☐ 1-5 | ☐ 1-5 | Pulsierend/rot? |
| Optimistic Update hilfreich | ☐ 1-5 | ☐ 1-5 | ☐ 1-5 | ☐ 1-5 | Sofortige Rückmeldung? |
| Fehlermeldungen verständlich | ☐ 1-5 | ☐ 1-5 | ☐ 1-5 | ☐ 1-5 | Klare Handlungsanweisung? |
| TTS-Audio-Qualität | ☐ 1-5 | ☐ 1-5 | ☐ 1-5 | ☐ 1-5 | Klar und verständlich? |

---

## Mobile-Browser-Tests (iOS/Android)

### iOS Safari (iPhone/iPad)

| Test-ID | Test-Beschreibung | iPhone (iOS 16) | iPhone (iOS 17) | iPad (iOS 16) | iPad (iOS 17) | Notizen |
|---------|-------------------|-----------------|-----------------|---------------|---------------|---------|
| MB-01 | Mikrofon-Berechtigung (iOS) | ☐ | ☐ | ☐ | ☐ | System-Dialog? |
| MB-02 | Recording während App-Wechsel | ☐ | ☐ | ☐ | ☐ | Unterbrechung? |
| MB-03 | TTS-Audio-Wiedergabe (iOS) | ☐ | ☐ | ☐ | ☐ | Lautstärke OK? |
| MB-04 | Performance (Audio-Konvertierung) | ___ ms | ___ ms | ___ ms | ___ ms | < 1000ms? |

### Android Chrome

| Test-ID | Test-Beschreibung | Android 12 | Android 13 | Android 14 | Notizen |
|---------|-------------------|------------|------------|------------|---------|
| MB-05 | Mikrofon-Berechtigung (Android) | ☐ | ☐ | ☐ | System-Dialog? |
| MB-06 | Recording während App-Wechsel | ☐ | ☐ | ☐ | Unterbrechung? |
| MB-07 | TTS-Audio-Wiedergabe (Android) | ☐ | ☐ | ☐ | Lautstärke OK? |
| MB-08 | Performance (Audio-Konvertierung) | ___ ms | ___ ms | ___ ms | < 1000ms? |

---

## Accessibility (A11y) Tests

| Test-ID | Test-Beschreibung | Chrome | Firefox | Safari | Edge | Notizen |
|---------|-------------------|--------|---------|--------|------|---------|
| A11Y-01 | Mikrofon-Icon mit aria-label | ☐ | ☐ | ☐ | ☐ | Screen-Reader-Test |
| A11Y-02 | Recording-Status akustisch wahrnehmbar | ☐ | ☐ | ☐ | ☐ | Sound/Voice-Feedback? |
| A11Y-03 | Fehlermeldungen screen-reader-freundlich | ☐ | ☐ | ☐ | ☐ | ARIA-Live-Region? |
| A11Y-04 | Keyboard-Navigation (Tab/Enter) | ☐ | ☐ | ☐ | ☐ | Mikrofon per Tastatur? |
| A11Y-05 | Farbkontrast (WCAG 2.1 AA) | ☐ | ☐ | ☐ | ☐ | Contrast Checker Tool |

---

## Regression-Tests (Nach Feature-Updates)

| Regression-ID | Bekannter Bug (behoben?) | Chrome | Firefox | Safari | Edge | Notizen |
|---------------|--------------------------|--------|---------|--------|------|---------|
| REG-01 | WebSocket "not alive" (Fix: Heartbeat) | ☐ | ☐ | ☐ | ☐ | 30s-Interval aktiv? |
| REG-02 | ESLint `any`-Types (Fix: Commit 3b3ba6f) | ☐ | ☐ | ☐ | ☐ | TypeScript-Build sauber? |
| REG-03 | [Platzhalter für zukünftige Bugs] | ☐ | ☐ | ☐ | ☐ | |

---

## Test-Zusammenfassung

### Gesamt-Bewertung

| Kategorie | Chrome | Firefox | Safari | Edge | Gesamt |
|-----------|--------|---------|--------|------|--------|
| Funktionalität (14 Tests) | ___/14 | ___/14 | ___/14 | ___/14 | ___% |
| Performance (3 Metriken) | ☐ ✅ / ☐ ❌ | ☐ ✅ / ☐ ❌ | ☐ ✅ / ☐ ❌ | ☐ ✅ / ☐ ❌ | ___% |
| Fehlerszenarien (8 Tests) | ___/8 | ___/8 | ___/8 | ___/8 | ___% |
| UX-Bewertung (5 Kriterien) | ___/25 | ___/25 | ___/25 | ___/25 | ___/100 |

### Finale Status

- **Chrome**: ☐ PASS / ☐ FAIL / ☐ NEEDS REVIEW
- **Firefox**: ☐ PASS / ☐ FAIL / ☐ NEEDS REVIEW
- **Safari**: ☐ PASS / ☐ FAIL / ☐ NEEDS REVIEW
- **Edge**: ☐ PASS / ☐ FAIL / ☐ NEEDS REVIEW

### Kritische Blocker (falls vorhanden)

1. **Blocker #1**: [Beschreibung] → ☐ FIXED / ☐ OPEN
2. **Blocker #2**: [Beschreibung] → ☐ FIXED / ☐ OPEN
3. **Blocker #3**: [Beschreibung] → ☐ FIXED / ☐ OPEN

### Empfehlung

- ☐ **READY FOR PRODUCTION** - Alle Tests bestanden
- ☐ **MINOR ISSUES** - Kleinere Probleme, aber produktionsreif
- ☐ **NEEDS FIXES** - Kritische Bugs müssen behoben werden
- ☐ **NOT READY** - Feature nicht produktionsreif

---

## CSV-Export für Excel/Google Sheets

**Anleitung**: Kopiere die Tabellen oben in Excel/Google Sheets für einfachere Bearbeitung.

**Alternative**: Nutze die bereitgestellte CSV-Datei `AUDIO_RECORDING_TEST_MATRIX.csv` (erstellt mit diesem Dokument).

---

**Test-Datum**: _______________
**Tester**: _______________
**Unterschrift**: _______________
