## Context

Die Spracheingabe-Funktion soll im Frontend aktiviert werden. Das Backend ist bereits vollständig implementiert und erwartet Audio-Dateien im WAV-Format (16kHz, 16-bit, Mono PCM) über multipart/form-data. Das Frontend hat die UI-Komponenten für Audio-Aufnahme, verwendet aber Browser-native MediaRecorder API, die formatinkompatible Ausgaben produziert (WebM/Opus, OGG/Opus, MP4/AAC je nach Browser).

**Technische Herausforderung:**
- Browser MediaRecorder: Erzeugt `audio/webm`, `audio/ogg`, oder `audio/mp4`
- Backend ASR Service: Erwartet `audio/wav` (16kHz, 16-bit, Mono PCM)
- Lösung: Client-seitige Format-Konvertierung mit Web Audio API

**Dokumentierte Lösung existiert:**
- `docs/frontend-integration/AudioRecorderWithWAVConversion.js` (vanillaJS)
- `docs/AUDIO_FORMAT_SOLUTION_GUIDE.md` (Implementierungsanleitung)
- Backend-Validierung bereits vorhanden (`pipeline_logic.py::validate_audio_input`)

**Stakeholders:**
- Frontend-Entwickler: Benötigen TypeScript-kompatible Implementierung
- Backend-Team: API bleibt unverändert, keine Rückwärtskompatibilitätsprobleme
- End-User: Erwarten funktionierende Audio-Kommunikation in allen gängigen Browsern

## Goals / Non-Goals

### Goals
1. **Funktionale Audio-Aufnahme** - User können über Mikrofon sprechen und Audio-Nachrichten senden
2. **Backend-Kompatibilität** - Garantierte WAV-Format-Ausgabe (16kHz, 16-bit, Mono PCM)
3. **Cross-Browser-Support** - Chrome, Firefox, Safari, Edge
4. **Type-Safe Implementation** - TypeScript mit vollständigen Type Definitions
5. **Error Resilience** - Graceful Handling von Mikrofonzugriff-Verweigerung, Konvertierungsfehlern, Upload-Fehlern
6. **Performance** - Konvertierung < 500ms für 10s Audio, kein UI-Blocking
7. **Memory-Safe** - Korrekte Cleanup von AudioContext, MediaStream, Blob-References

### Non-Goals
1. **Backend-Format-Erweiterung** - Backend wird nicht angepasst, um zusätzliche Formate zu akzeptieren
2. **Audio-Editing** - Keine Trim/Cut/Filter-Funktionen (nur Record → Convert → Upload)
3. **Offline-Recording** - Keine lokale Speicherung oder Background-Recording
4. **Advanced Audio-Features** - Kein Echo-Cancellation-Tuning, kein Noise-Gate (Browser-Standard nutzen)
5. **Multi-Track-Recording** - Nur Mono-Aufnahme (wie Backend erwartet)

## Decisions

### Decision 1: Client-Side WAV Conversion (Primary), Server-Side Fallback (Optional Future)

**Entscheidung:** WAV-Konvertierung erfolgt primär im Browser. Server-seitige Konvertierung als optionaler Fallback wird für Phase 2 evaluiert.

**Rationale für Frontend-First Approach:**
- ✅ **Keine Backend-Änderungen für MVP** - Existierende API bleibt unverändert, schnelleres Time-to-Market
- ✅ **Reduzierte Server-Last** - GPU/CPU-Ressourcen (20GB VRAM geteilt zwischen ASR/Translation/TTS) bleiben für ML-Inferenz
- ✅ **Sofortige Validierung** - Format-Fehler vor Upload erkennbar, bessere UX
- ✅ **Bessere Skalierung** - Last verteilt auf Client-Geräte statt zentralem Server
- ✅ **Lower Latency** - 200-500ms lokale Konvertierung ohne Netzwerk-Roundtrip
- ✅ **Standard-Kompatibilität** - Web Audio API ist in allen Ziel-Browsern stabil verfügbar

**Alternatives Considered:**

1. **Pure Server-Side FFmpeg Conversion**
   - Pro: Konsistente Qualität, Support für alle Formate, einfacheres Frontend
   - Contra: Backend-Änderungen nötig, FFmpeg-Dependency, höhere Server-Last, zusätzlicher Bottleneck bei Skalierung
   - **Entscheidung:** Nicht für MVP, aber als Fallback-Option für Phase 2 sinnvoll

2. **Hybrid Approach (Frontend + Server Fallback)**
   - Pro: Beste Robustheit, funktioniert auch bei Frontend-Fehlern, graceful degradation
   - Contra: Höhere Komplexität, Backend-Änderungen erforderlich
   - **Entscheidung:** Empfehlenswert für Phase 2 nach MVP-Validierung
   - **Implementation Path:**
     ```
     Frontend versucht WAV-Konvertierung
       ├─ Erfolg (95% der Fälle) → Upload als WAV
       └─ Fehler/Unsupported → Upload Original-Format
                                Backend erkennt Format → FFmpeg-Konvertierung → ASR
     ```

3. **WebCodecs API**
   - Pro: Native Browser-Konvertierung ohne Web Audio API Overhead
   - Contra: Safari-Support fehlt (Stand Nov 2025), experimental status
   - **Entscheidung:** Zu früh, Web Audio API ist ausgereifter

**Trade-off Analyse:**

| Aspekt | Frontend-Only | Server-Only | Hybrid |
|--------|--------------|-------------|--------|
| MVP Speed | ✅ Schnell | ❌ Backend-Arbeit | ⚠️ Mittel |
| Server-Last | ✅ Minimal | ❌ Hoch | ⚠️ Fallback-Last |
| Browser-Kompatibilität | ✅ Gut (Web Audio) | ✅ Perfekt | ✅ Perfekt |
| Wartbarkeit | ✅ Frontend-Only | ✅ Server-Only | ⚠️ Beide Seiten |
| Robustheit | ⚠️ Client-abhängig | ✅ Konsistent | ✅ Best |
| Latenz | ✅ 200-500ms | ⚠️ 500ms + Network | ✅ 200-500ms |

**Empfehlung für Phase 2 (Post-MVP):**
Nach erfolgreicher MVP-Validierung Backend um optionale Format-Konvertierung erweitern:
- `enhanced_audio_validation.py` bereits vorhanden (siehe Docs)
- FFmpeg in `api_gateway` Docker-Image installieren
- Backend erkennt automatisch Non-WAV und konvertiert transparent
- Frontend sendet weiterhin primär WAV, kann aber auch Original-Format senden
- Monitoring zeigt Konvertierungs-Rate (Frontend vs. Backend)

### Decision 2: TypeScript-Only Implementation

**Entscheidung:** Neue Implementierung in TypeScript, keine JavaScript-Portierung der Docs-Version.

**Rationale:**
- ✅ **Type Safety** - Compile-Time-Fehler statt Runtime-Bugs
- ✅ **IDE Support** - IntelliSense, Auto-Completion, Refactoring
- ✅ **Maintainability** - Selbst-dokumentierender Code
- ✅ **Konsistenz** - Rest des Frontend ist TypeScript

**Implementation Details:**
```typescript
interface AudioRecorderConfig {
  sampleRate: number;      // 16000 für Backend
  bitDepth: 16 | 8;        // 16-bit bevorzugt
  channels: 1 | 2;         // 1 = Mono
  maxDurationMs: number;   // 20000 (20s Limit)
}

interface WAVConversionResult {
  valid: boolean;
  wavBlob?: Blob;
  error?: string;
  format?: {
    sampleRate: number;
    channels: number;
    bitDepth: number;
    fileSize: number;
  };
}
```

### Decision 3: Isolated Utility Module

**Entscheidung:** `AudioRecorderWithWAVConversion.ts` als eigenständiges, wiederverwendbares Modul.

**Rationale:**
- ✅ **Separation of Concerns** - Audio-Logic getrennt von React-Komponenten
- ✅ **Testability** - Utility ist isoliert testbar ohne React-Testing-Library
- ✅ **Reusability** - Kann in Admin- und Customer-Komponenten verwendet werden
- ✅ **Performance** - Kein Re-Render-Overhead durch React

**Architecture:**
```
src/
├── utils/
│   └── AudioRecorderWithWAVConversion.ts   # Standalone utility
├── components/
│   └── MessageInput.tsx                    # React integration
└── services/
    └── MessageService.ts                   # API calls
```

### Decision 4: FormData Upload (Not Base64 JSON)

**Entscheidung:** Audio-Upload via `multipart/form-data`, nicht als Base64-encoded JSON.

**Rationale:**
- ✅ **Backend-Kompatibilität** - API erwartet bereits `multipart/form-data`
- ✅ **Efficiency** - Binärdaten, keine Base64-Overhead (~33% größer)
- ✅ **Standard-Konform** - File-Uploads sind idomatisch via FormData
- ✅ **Progress-Tracking** - XMLHttpRequest.upload.progress Events verfügbar

**Implementation:**
```typescript
const formData = new FormData();
formData.append('file', wavBlob, 'recording.wav');
formData.append('source_lang', sourceLanguage);
formData.append('target_lang', targetLanguage);
formData.append('client_type', clientType);
```

### Decision 5: No Additional Dependencies

**Entscheidung:** Nur Browser-native APIs verwenden, keine zusätzlichen npm-Packages.

**Rationale:**
- ✅ **Bundle Size** - Keine zusätzlichen KB für Audio-Libraries
- ✅ **Security** - Keine Third-Party-Dependencies mit CVEs
- ✅ **Browser Support** - Web Audio API ist in allen Ziel-Browsern verfügbar
- ✅ **Maintenance** - Keine Dependency-Updates nötig

**Verwendete Browser-APIs:**
- `navigator.mediaDevices.getUserMedia()` - Mikrofonzugriff
- `MediaRecorder` - Audio-Aufnahme in Browser-nativem Format
- `AudioContext` / `decodeAudioData()` - Audio-Dekodierung
- `Float32Array` / `DataView` - WAV-Encoding
- `Blob` / `FileReader` - Binary Data Handling

## Risks / Trade-offs

### Risk 1: Browser-Compatibility Issues
**Risk:** Safari oder ältere Browser könnten Web Audio API unterschiedlich implementieren.

**Mitigation:**
- Umfassives Browser-Testing (Chrome, Firefox, Safari, Edge)
- Fallback-Chain für MediaRecorder-Formate
- Graceful Degradation mit aussagekräftigen Fehlermeldungen
- User-Agent-basierte Warnung bei unsupporteten Browsern (optional)

**Trade-off:** Mehr Testaufwand vs. robuste Lösung für alle Browser

### Risk 2: Performance auf Mobile Devices
**Risk:** WAV-Konvertierung könnte auf Low-End-Smartphones zu langsam sein.

**Mitigation:**
- Asynchrone Verarbeitung mit `async/await`
- Progress-Indicator während Konvertierung
- Max. 20s Audio-Limit (reduziert Datenmenge)
- Memory-effizientes Streaming statt vollständigem Buffer

**Trade-off:** Etwas höhere Latenz auf Mobile vs. garantiert funktionierendes Format

### Risk 3: Memory Leaks durch Audio-Ressourcen
**Risk:** AudioContext, MediaStream, Blobs könnten nicht korrekt aufgeräumt werden.

**Mitigation:**
- Expliziter `cleanup()` Call in `useEffect` Cleanup
- `audioContext.close()` nach Konvertierung
- `stream.getTracks().forEach(track => track.stop())` nach Recording
- React Refs für Ressourcen-Tracking

**Trade-off:** Zusätzlicher Cleanup-Code vs. Memory-Stabilität

### Risk 4: WAV-File-Size vs. Network Bandwidth
**Risk:** WAV-Dateien sind größer als Opus/AAC (keine Kompression).

**Context:**
- 10s Audio @ 16kHz Mono 16-bit = ~320KB (unkomprimiert)
- Vergleich: WebM/Opus @ 128kbps = ~160KB (komprimiert)

**Mitigation:**
- Audio-Limit auf 20s (max ~640KB)
- Mono statt Stereo (halbiert Größe)
- 16kHz statt 44.1kHz (reduziert Größe um ~64%)
- HTTP/2 mit Traefik (bessere Compression)

**Trade-off:** Größere Uploads vs. Backend-Kompatibilität und einfachere Implementierung

## Migration Plan

**Phase 1: Development & Testing (1-2 Tage)**
1. TypeScript-Utility implementieren
2. MessageInput-Integration
3. Unit & Integration Tests
4. Cross-Browser-Testing

**Phase 2: Staging Deployment (0.5 Tag)**
1. Frontend-Build mit neuem Code
2. Deployment auf Staging-Umgebung
3. E2E-Tests mit echtem Backend
4. Performance-Validierung

**Phase 3: Production Rollout (0.5 Tag)**
1. Production-Build
2. Docker-Image-Build
3. Deployment auf Production
4. Monitoring für erste Stunden

**Rollback-Plan:**
- Frontend-Rollback auf vorherige Version (Docker-Image-Tag)
- Keine Backend-Änderungen nötig
- Keine Datenmigration erforderlich
- Rollback-Zeit: < 5 Minuten

**Success Metrics:**
- Audio-Upload-Success-Rate > 95%
- WAV-Konvertierung < 500ms für 10s Audio
- Keine Memory-Leaks nach 1h kontinuierlicher Nutzung
- Cross-Browser-Funktionalität in Chrome/Firefox/Safari/Edge

## Open Questions

1. **Sollen wir Audio-Format-Warnung zeigen?**
   - z.B. "Safari unterstützt möglicherweise nicht alle Features"
   - Entscheidung: Nein, außer bei tatsächlichem Fehler

2. **Max. Audio-Duration: 20s oder länger?**
   - Backend hat keine strikte Obergrenze (nur 120s technisch)
   - Frontend-UX: 20s ist für Conversation-Snippets angemessen
   - Entscheidung: 20s beibehalten (wie in Docs dokumentiert)

3. **Soll Konvertierung Web Worker nutzen?**
   - Pro: UI-Thread bleibt frei
   - Contra: Zusätzliche Komplexität, Audio-API in Worker ist experimentell
   - Entscheidung: Nein für MVP, async/await reicht für < 500ms Operations

4. **Audio-Preview vor Upload?**
   - Pro: User kann überprüfen, ob Aufnahme korrekt ist
   - Contra: Zusätzliche UI-Komplexität, verlängert User-Flow
   - Entscheidung: Nein für MVP, direkter Upload nach Recording-Stop

5. **Soll Recording pausierbar sein?**
   - Pro: Flexibilität für längere Nachrichten
   - Contra: Komplexere State-Machine, mehr Edge-Cases
   - Entscheidung: Nein für MVP, einfaches Start/Stop-Pattern
