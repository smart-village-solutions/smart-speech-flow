## 1. Vorbereitung und Analyse
- [ ] 1.1 Bestehenden Frontend-Code analysieren (`MessageInput.tsx`)
- [ ] 1.2 Backend-API-Kontrakt für Audio-Upload verifizieren (`/api/session/{sessionId}/message`)
- [ ] 1.3 Dokumentierte Lösung aus `docs/frontend-integration/AudioRecorderWithWAVConversion.js` reviewen
- [ ] 1.4 TypeScript-Interfaces für Audio-Upload definieren
- [ ] 1.5 Commit Changes

## 2. WAV-Konvertierungs-Utility implementieren
- [ ] 2.1 Neue Datei `src/utils/AudioRecorderWithWAVConversion.ts` erstellen
- [ ] 2.2 MediaRecorder-Wrapper mit Browser-Format-Erkennung implementieren
- [ ] 2.3 Web Audio API Integration für Audio-Dekodierung
- [ ] 2.4 PCM Resampling-Logik (beliebige Samplerate → 16kHz Mono)
- [ ] 2.5 WAV-Header-Generierung (RIFF/WAVE/fmt/data chunks)
- [ ] 2.6 WAV-Format-Validierung implementieren
- [ ] 2.7 Error-Handling für Mikrofonzugriff und Konvertierungsfehler
- [ ] 2.8 TypeScript-Typen und Interfaces definieren
- [ ] 2.9 Commit Changes

## 3. MessageInput-Komponente erweitern
- [ ] 3.1 Import der `AudioRecorderWithWAVConversion` Utility
- [ ] 3.2 State-Management für Konvertierungs-Status erweitern
- [ ] 3.3 `sendAudioMessage()` Funktion implementieren
  - [ ] 3.3.1 FormData-Objekt mit WAV-Blob erstellen
  - [ ] 3.3.2 Korrekte Parameter hinzufügen (source_lang, target_lang, client_type)
  - [ ] 3.3.3 POST-Request an `/api/session/{sessionId}/message` senden
  - [ ] 3.3.4 Response-Handling und WebSocket-Integration
- [ ] 3.4 `startRecording()` Funktion mit WAV-Konvertierung verknüpfen
- [ ] 3.5 Error-Handling und User-Feedback implementieren
- [ ] 3.6 Optimistische UI-Updates während Upload
- [ ] 3.7 Commit Changes

## 4. Integration und UI-Verbesserungen
- [ ] 4.1 Ladezustand während WAV-Konvertierung anzeigen
- [ ] 4.2 Upload-Progress-Feedback (optional)
- [ ] 4.3 Error-Messages für verschiedene Fehlerfälle
  - [ ] 4.3.1 Mikrofon-Permission verweigert
  - [ ] 4.3.2 WAV-Konvertierung fehlgeschlagen
  - [ ] 4.3.3 Upload-Fehler (Netzwerk, Backend)
  - [ ] 4.3.4 Ungültige Session oder fehlende Parameter
- [ ] 4.4 Success-Feedback nach erfolgreichem Upload
- [ ] 4.5 Commit Changes

## 5. Testing
- [ ] 5.1 Unit Tests für WAV-Konvertierungs-Utility
  - [ ] 5.1.1 WAV-Header-Generierung
  - [ ] 5.1.2 Resampling-Logik
  - [ ] 5.1.3 Format-Validierung
  - [ ] 5.1.4 Error-Cases
- [ ] 5.2 Integration Tests für Audio-Upload-Flow
  - [ ] 5.2.1 Mock MediaRecorder
  - [ ] 5.2.2 Mock Backend API Response
  - [ ] 5.2.3 WebSocket-Message-Handling
- [ ] 5.3 Manuelles Cross-Browser-Testing
  - [ ] 5.3.1 Chrome (WebM/Opus)
  - [ ] 5.3.2 Firefox (OGG/Opus)
  - [ ] 5.3.3 Safari (MP4/AAC)
  - [ ] 5.3.4 Edge (WebM/Opus)
- [ ] 5.4 End-to-End Test mit echtem Backend
  - [ ] 5.4.1 Audio-Aufnahme → Upload → ASR → Translation → TTS
  - [ ] 5.4.2 WebSocket-Broadcast an beide Clients
  - [ ] 5.4.3 Audio-Wiedergabe im UI
  - [ ] 5.5 Commit Changes

## 6. Dokumentation
- [ ] 6.1 Code-Kommentare und JSDoc für öffentliche APIs
- [ ] 6.2 README-Update mit Audio-Feature-Beschreibung
- [ ] 6.3 Troubleshooting-Guide für häufige Probleme
- [ ] 6.4 Browser-Kompatibilitäts-Matrix aktualisieren
- [ ] 6.5 Commit Changes

## 7. Quality Assurance
- [ ] 7.1 TypeScript-Compilation ohne Errors
- [ ] 7.2 ESLint/Prettier-Checks bestehen
- [ ] 7.3 Code-Review-Ready: Clean Code, keine TODOs
- [ ] 7.4 Performance-Check: Konvertierung < 500ms für 10s Audio
- [ ] 7.5 Memory-Leak-Check: AudioContext und MediaStream richtig aufräumen
- [ ] 7.6 Commit Changes

## 8. Deployment-Vorbereitung
- [ ] 8.1 Production-Build testen
- [ ] 8.2 Docker-Image-Build verifizieren
- [ ] 8.3 Rollback-Strategie dokumentieren
- [ ] 8.4 Deployment-Checklist erstellen
- [ ] 8.5 Commit Changes

## 9. Post-Deployment
- [ ] 9.1 Monitoring: Error-Rate für Audio-Uploads überwachen
- [ ] 9.2 User-Feedback sammeln
- [ ] 9.3 Performance-Metriken analysieren
- [ ] 9.4 Eventuell notwendige Optimierungen identifizieren
- [ ] 9.5 Commit Changes
