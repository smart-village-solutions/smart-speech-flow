# Change: Add Frontend Audio Recording with WAV Conversion

## Why
Die Spracheingabe-Funktion im Frontend ist derzeit nicht funktionsfähig. Obwohl die UI-Komponenten für Audio-Aufnahme existieren und das Backend vollständig für Audio-Verarbeitung vorbereitet ist, fehlt die kritische Konvertierungslogik zwischen Browser-Audio-Format (WebM/Opus) und dem vom Backend erwarteten WAV-Format (16kHz, 16-bit, Mono PCM).

**Aktueller Zustand:**
- Backend: ✅ Vollständig implementiert (Audio-Upload, Validierung, ASR→Translation→TTS Pipeline)
- Frontend UI: ✅ Aufnahme-Button, Timer, MediaRecorder vorhanden
- Frontend Logic: ❌ `sendAudioMessage()` gibt nur TODO-Fehlermeldung zurück
- Format-Konvertierung: ❌ Nicht implementiert

**Problem:**
Browser-native MediaRecorder API erzeugt `audio/webm` (Chrome/Edge/Firefox) oder `audio/mp4` (Safari), während das Backend WAV-Format mit spezifischen Parametern erwartet. Ohne clientseitige Format-Konvertierung schlägt der Upload fehl.

## What Changes

### Frontend (React/TypeScript)
- **NEUE DATEI**: `src/utils/AudioRecorderWithWAVConversion.ts` - WAV-Konvertierungs-Utility
  - MediaRecorder-Integration mit Browser-Format-Erkennung
  - Web Audio API für Dekodierung und Resampling (16kHz, Mono)
  - PCM WAV-Header-Generierung (RIFF/WAVE Format)
  - Integrierte Validierung des generierten WAV-Formats
  - Upload-Helper mit FormData für Backend-Integration

- **ÄNDERUNG**: `src/components/MessageInput.tsx`
  - Ersetze TODO-Stub `sendAudioMessage()` mit funktionaler Implementierung
  - Integration der `AudioRecorderWithWAVConversion` Utility
  - FormData-basierter Upload mit `multipart/form-data`
  - Error-Handling für Mikrofonzugriff, Konvertierung und Upload
  - Optimistische UI-Updates während der Verarbeitung

### Technische Details
- **Keine Backend-Änderungen** - Verwendet existierende `/api/session/{sessionId}/message` Endpunkte
- **Browser-Kompatibilität** - Fallback-Chain für MediaRecorder-Formate (WebM → OGG → MP4 → WAV)
- **Performance** - Client-seitige Konvertierung vermeidet Server-Last
- **Audio-Specs** - Garantiert Backend-konforme Ausgabe (16kHz, 16-bit, Mono)

### Betroffene Komponenten
1. **Neue Utility**: Audio-Konvertierungs-Logik (vollständig isoliert und testbar)
2. **MessageInput**: Integration der Konvertierung + Upload-Implementierung
3. **Keine API-Änderungen**: Backend bleibt unverändert

## Impact

### Affected Specs
- **Frontend SPA Application** (`add-frontend-spa-application`) - MODIFIED
  - Requirement "Message Input Component" wird erweitert um funktionale Audio-Aufnahme
  - Neues Sub-Requirement für WAV-Konvertierungs-Utility

### Affected Code
- `services/frontend/src/components/MessageInput.tsx` - Implementierung der Audio-Upload-Logik
- `services/frontend/src/utils/AudioRecorderWithWAVConversion.ts` - Neue Utility-Datei
- `services/frontend/src/services/MessageService.ts` - Möglicherweise TypeScript-Interface-Ergänzung

### Breaking Changes
**Keine**. Diese Änderung ist vollständig abwärtskompatibel:
- Backend-API bleibt unverändert
- Bestehende Text-Nachrichten funktionieren weiterhin
- Audio-Feature wird aktiviert, war aber zuvor nicht funktional

### Migration Required
**Keine**. Die Änderung ist eine reine Feature-Aktivierung ohne Datenmigration oder API-Breaking-Changes.

### User-Visible Changes
- ✅ Audio-Aufnahme-Button wird funktional
- ✅ Aufgenommenes Audio wird korrekt an Backend gesendet
- ✅ ASR → Translation → TTS Pipeline wird für Audio-Nachrichten aktiv
- ✅ WebSocket-Broadcast von Audio-Antworten funktioniert

### Testing Strategy
- **Unit Tests**: WAV-Konvertierungs-Logik (Header, Resampling, Format-Validierung)
- **Integration Tests**: Upload-Flow mit Mock-Backend
- **Manual Browser Testing**: Chrome, Firefox, Safari, Edge
- **Cross-Browser Validation**: Format-Fallback-Chain testen
- **Error Cases**: Mikrofon-Permission-Denial, Konvertierungsfehler, Upload-Fehler

### Deployment Notes
- **Frontend-Only**: Nur Frontend-Container muss neu gebaut werden
- **Zero-Downtime**: Keine Backend-Änderungen erforderlich
- **Rollback-Safe**: Altes Frontend zeigt weiterhin "Audio nicht unterstützt" Meldung
