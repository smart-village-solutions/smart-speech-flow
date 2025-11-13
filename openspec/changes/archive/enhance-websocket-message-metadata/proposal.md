# Proposal: Enhance WebSocket Message Metadata

**Change ID:** `enhance-websocket-message-metadata`
**Status:** 🟡 Draft
**Created:** 2025-11-05
**Author:** AI Assistant (via User Request)

## Why

### Business Value

Das Frontend benötigt vollständige Transparenz über den Translation-Pipeline-Prozess, um bessere User Experience und Debugging-Möglichkeiten zu bieten. Aktuell erhält das Frontend nur das finale Ergebnis ohne Kontext über Zwischenschritte, was folgende Probleme verursacht:

1. **Debugging unmöglich:** Bei Fehlern weiß das Frontend nicht, welcher Service versagt hat
2. **Keine Performance-Insights:** User sehen nicht, warum eine Übersetzung länger dauert
3. **Fehlende Flexibilität:** Frontend kann nicht zwischen refinierter und Original-Übersetzung wählen
4. **Audit-Trail fehlt:** Keine Nachvollziehbarkeit der Transformationen

### User Impact

- **Besseres Debugging:** Support-Team kann genau sehen, wo Probleme auftreten
- **Transparenz:** User verstehen, welche Schritte die Translation durchläuft
- **Qualitätskontrolle:** Vergleich zwischen Original-ASR und finaler Übersetzung möglich
- **Original-Audio-Zugriff:** User können Original-Aufnahmen anhören/herunterladen

### Technical Value

- **Data Collection (Prototyp-Phase):** Vollständige Erfassung aller Pipeline-Daten für Qualitätsverbesserungen
- **Performance-Monitoring:** Identifikation von Bottlenecks durch Zeitstempel-Analyse
- **Fehleranalyse:** Detaillierte Logs ermöglichen schnellere Problemlösung

## Problem Statement
Das aktuelle WebSocket-Nachrichtenformat liefert nur das finale Ergebnis der Translation-Pipeline (übersetzter Text + Audio). Das Frontend erhält keine Zwischenschritte und Pipeline-Metadaten, die für folgende Use Cases benötigt werden:

### Current Limitations

1. **Fehlende Transparenz:** Frontend kann nicht sehen, welche Zwischenschritte die Pipeline durchlaufen hat
2. **Debugging erschwert:** Bei Fehlern fehlt Kontext (welcher Service hat versagt?)
3. **Keine Flexibilität:** Frontend kann nicht entscheiden, ob es refinierte oder nicht-refinierte Übersetzung anzeigen will
4. **Fehlende Audit-Daten:** Originalsprache und Zwischenergebnisse sind nicht verfügbar
5. **Performance-Analysen unmöglich:** Frontend hat keine Zeitstempel der einzelnen Pipeline-Schritte

### Current WebSocket Message Format

```json
{
  "type": "message",
  "role": "receiver_message",
  "message_id": "uuid-1234",
  "session_id": "ABC123",
  "text": "Hello, how can I help?",
  "sender": "admin",
  "timestamp": "2025-11-05T20:01:00Z",
  "audio_available": true,
  "audio_url": "/api/audio/uuid-1234.wav",
  "source_lang": "de",
  "target_lang": "en"
}
```

**Was fehlt:**
- Ausgangssprache (source_language) ✅ **BEREITS VORHANDEN** als `source_lang`
- Original Audio-Aufnahme des Sprechers
- Erkannter Text **vor** der Übersetzung (ASR-Output)
- Übersetzter Text **vor** dem Refinement (M2M100-Output)
- Übersetzter Text **nach** dem Refinement (Ollama-Output)
- Neue Audiofile ✅ **BEREITS VORHANDEN** als `audio_url`
- Zielsprache ✅ **BEREITS VORHANDEN** als `target_lang`
- Zeitstempel der einzelnen Pipeline-Schritte

## Proposed Solution

### Enhanced WebSocket Message Format

Erweitere die WebSocket-Nachricht um eine neue `pipeline_metadata`-Struktur, die alle Zwischenschritte und Zeitstempel enthält:

```json
{
  "type": "message",
  "role": "receiver_message",
  "message_id": "uuid-1234",
  "session_id": "ABC123",

  // EXISTING FIELDS (unchanged)
  "text": "Hello, how can I help?",
  "sender": "admin",
  "timestamp": "2025-11-05T20:01:00Z",
  "audio_available": true,
  "audio_url": "/api/audio/uuid-1234.wav",
  "source_lang": "de",
  "target_lang": "en",

  // NEW: Pipeline Metadata
  "pipeline_metadata": {
    // Original Input
    "input": {
      "type": "audio",                          // "audio" | "text"
      "audio_url": "/api/audio/input_uuid.wav", // Original Speaker Audio
      "source_lang": "de"
    },

    // Pipeline Steps with Timestamps
    "steps": [
      {
        "name": "asr",
        "input": {"audio_url": "/api/audio/input_uuid.wav"},
        "output": {
          "text": "Hallo, wie kann ich helfen?",
          "confidence": 0.95
        },
        "started_at": "2025-11-05T20:00:55.000Z",
        "completed_at": "2025-11-05T20:00:57.500Z",
        "duration_ms": 2500
      },
      {
        "name": "translation",
        "input": {
          "text": "Hallo, wie kann ich helfen?",
          "source_lang": "de",
          "target_lang": "en"
        },
        "output": {
          "text": "Hello, how can I help?",
          "tts_text": "Hello, how can I help?",  // Romanized for TTS
          "model": "m2m100_1.2B"
        },
        "started_at": "2025-11-05T20:00:57.500Z",
        "completed_at": "2025-11-05T20:00:58.000Z",
        "duration_ms": 500
      },
      {
        "name": "refinement",
        "input": {
          "text": "Hello, how can I help?",
          "enabled": true
        },
        "output": {
          "text": "Hello, how may I assist you?",
          "changed": true,
          "model": "ollama/llama3"
        },
        "started_at": "2025-11-05T20:00:58.000Z",
        "completed_at": "2025-11-05T20:00:59.200Z",
        "duration_ms": 1200
      },
      {
        "name": "tts",
        "input": {
          "text": "Hello, how may I assist you?",
          "lang": "en"
        },
        "output": {
          "audio_url": "/api/audio/uuid-1234.wav",
          "format": "wav",
          "sample_rate": 16000,
          "duration_seconds": 2.5
        },
        "started_at": "2025-11-05T20:00:59.200Z",
        "completed_at": "2025-11-05T20:01:00.000Z",
        "duration_ms": 800
      }
    ],

    // Summary
    "total_duration_ms": 5000,
    "pipeline_started_at": "2025-11-05T20:00:55.000Z",
    "pipeline_completed_at": "2025-11-05T20:01:00.000Z"
  }
}
```

### Key Benefits

1. **Frontend-Flexibilität:** Frontend entscheidet, welche Daten angezeigt werden:
   - Nur finale Übersetzung (Standard)
   - Original-Text zur Bestätigung
   - Vergleich: Vorher/Nachher Refinement
   - Performance-Metriken der Pipeline

2. **Debugging:** Bei Fehlern kann Frontend/Support genau sehen, welcher Schritt fehlgeschlagen ist

3. **Audit Trail:** Vollständige Nachverfolgbarkeit aller Transformationen

4. **Performance-Monitoring:** Frontend kann langsame Schritte identifizieren und dem User Feedback geben

5. **Rückwärtskompatibilität:** Bestehende Felder bleiben unverändert, neue Daten sind optional

## Implementation Strategy

### Phase 1: Backend - Pipeline Metadata Collection ✅ (Teilweise vorhanden)

**Status:** Pipeline-Logic sammelt bereits `debug_info` mit allen Schritten!

Siehe `services/api_gateway/pipeline_logic.py`:
- `process_wav()` - Lines 975-1155
- `process_text_pipeline()` - Lines 675-870

**Aktuelles Debug-Format:**
```python
debug_info = {
    "frontend_input": {...},
    "steps": [
        {
            "step": "ASR",
            "input": {"lang": source_lang},
            "output": asr_text,
            "error": asr_json.get("error"),
            "duration": 2.5
        },
        # ... weitere Schritte
    ],
    "total_duration": 5.0
}
```

**Was zu tun ist:**
1. ✅ Debug-Info wird bereits gesammelt
2. ❌ Zeitstempel (started_at/completed_at) fehlen noch
3. ❌ Original Audio-URL wird nicht gespeichert
4. ❌ Debug-Info wird nicht in SessionMessage gespeichert

### Phase 2: Backend - SessionMessage Enhancement

Erweitere `SessionMessage` Dataclass um Pipeline-Metadaten:

```python
@dataclass
class SessionMessage:
    id: str
    sender: ClientType
    original_text: str
    translated_text: str
    audio_base64: Optional[str]
    source_lang: str
    target_lang: str
    timestamp: datetime

    # NEW: Pipeline Metadata
    pipeline_metadata: Optional[Dict[str, Any]] = None
    original_audio_url: Optional[str] = None  # Input audio URL
```

### Phase 3: Backend - WebSocket Broadcasting

Erweitere `broadcast_with_differentiated_content()` um Pipeline-Metadaten:

```python
# In services/api_gateway/websocket.py
receiver_message = {
    "type": MessageType.MESSAGE.value,
    "message_id": message.id,
    "session_id": session_id,
    "text": message.translated_text,
    "source_lang": message.source_lang,
    "target_lang": message.target_lang,
    "sender": message.sender.value,
    "timestamp": message.timestamp.isoformat(),
    "audio_available": message.audio_base64 is not None,
    "audio_url": f"/api/audio/{message.id}.wav" if message.audio_base64 else None,
    "role": "receiver_message",

    # NEW: Pipeline Metadata
    "pipeline_metadata": message.pipeline_metadata,
}
```

### Phase 4: Frontend - Opt-in Usage

Frontend kann Metadaten optional nutzen:

```typescript
interface WebSocketMessage {
  type: string;
  role: string;
  text: string;
  // ... existing fields

  // NEW: Optional metadata
  pipeline_metadata?: {
    input: {
      type: "audio" | "text";
      audio_url?: string;
      source_lang: string;
    };
    steps: PipelineStep[];
    total_duration_ms: number;
    pipeline_started_at: string;
    pipeline_completed_at: string;
  };
}

// Example: Show performance warning
if (msg.pipeline_metadata?.total_duration_ms > 10000) {
  console.warn("⚠️ Translation took longer than 10s");
}

// Example: Show original audio for debugging
if (msg.pipeline_metadata?.input.audio_url) {
  console.log("🔊 Original audio:", msg.pipeline_metadata.input.audio_url);
}
```

## Migration Path

### Backward Compatibility

✅ **100% Backward Compatible**

- Alle bestehenden Felder bleiben unverändert
- `pipeline_metadata` ist **optional**
- Alte Clients ignorieren einfach das neue Feld
- Neue Clients können progressive enhancement nutzen

### Rollout Strategy

1. **Week 1:** Backend-Implementation
   - Collect pipeline metadata in pipeline_logic.py
   - Store in SessionMessage
   - Include in WebSocket messages

2. **Week 2:** Testing & Validation
   - E2E tests verify metadata presence
   - Performance tests ensure no overhead
   - Documentation updates

3. **Week 3:** Frontend Integration (Optional)
   - Frontend teams can start using metadata
   - No breaking changes required
   - Gradual adoption possible

## Success Criteria

- [ ] WebSocket messages include `pipeline_metadata` field (always enabled)
- [ ] All pipeline steps (ASR, Translation, Refinement, TTS) are tracked with timestamps
- [ ] Timestamps (started_at, completed_at, duration_ms) are accurate
- [ ] Original audio is stored in `/data/audio/original/` directory
- [ ] Original audio URL is accessible via `/api/audio/input_{message_id}.wav`
- [ ] Cleanup job deletes audio files after 24 hours
- [ ] Disk space monitoring is configured
- [ ] 100% backward compatibility (existing clients work unchanged)
- [ ] E2E tests validate metadata structure
- [ ] Documentation updated (frontend_api.md, WEBSOCKET_MESSAGE_ROLES.md)

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Message size increase | Medium | Acceptable for prototype phase; can be optimized later |
| Performance overhead | Low | Metadata collection already happens (debug_info) |
| Breaking changes | High | ✅ 100% backward compatible design |
| Frontend confusion | Medium | Clear documentation + examples |
| Disk space exhaustion | High | 24h cleanup job + monitoring alerts |
| Privacy concerns | Medium | 24h retention period; future: configurable/disable |

## Related Documents

- `/docs/frontend_api.md` - WebSocket Message Format
- `/docs/WEBSOCKET_MESSAGE_ROLES.md` - Message Roles Documentation
- `/services/api_gateway/pipeline_logic.py` - Pipeline Implementation
- `/services/api_gateway/session_manager.py` - SessionMessage Model

## Audio Storage Strategy

### Original Audio Files (Input)

**Storage Location:** Lokales Dateisystem unter `/data/audio/original/`

**Struktur:**
```
/data/audio/
├── original/           # Original-Aufnahmen der Sprecher
│   ├── input_uuid-1.wav
│   ├── input_uuid-2.wav
│   └── ...
└── translated/         # Übersetzte TTS-Audio (bestehend)
    ├── uuid-1.wav
    ├── uuid-2.wav
    └── ...
```

**Retention Policy:**
- ✅ **24 Stunden:** Audio-Dateien werden 24h nach Erstellung automatisch gelöscht
- ✅ **Cleanup-Job:** Cronjob oder Background-Task läuft stündlich und löscht veraltete Dateien
- ✅ **Disk Space Management:** Monitoring für verfügbaren Speicherplatz

**Begründung:**
- Prototyp-Phase: Vollständige Datenerfassung für Debugging und Qualitätssicherung
- Später: Datenschutz-Erhöhung durch kürzere Retention oder Deaktivierung

### Pipeline Metadata Collection

**Status:** ✅ **IMMER AKTIVIERT** (Prototyp-Phase)

- Alle Pipeline-Schritte werden mit Zeitstempeln erfasst
- Original-Audio wird persistent gespeichert (24h Retention)
- Zwischenergebnisse (ASR, Translation vor/nach Refinement) werden gespeichert

**Datenschutz-Roadmap:**
- **Phase 1 (jetzt):** Vollständige Metadaten-Erfassung für alle Nachrichten
- **Phase 2 (später):** Optional deaktivierbar via Environment-Variable
- **Phase 3 (Produktion):** Standardmäßig deaktiviert, nur auf Anfrage aktiviert

## Open Questions

1. **Should we include metadata in `sender_confirmation` messages?**
   - ✅ **ANSWERED:** Yes, same metadata for consistency

2. **Should metadata be filterable via WebSocket connection params?**
   - Example: `ws://server/ws/ABC123/customer?include_metadata=false`
   - Proposal: Not in Phase 1, add later if needed (Phase 2)
   - ✅ **ANSWERED:** Not in Phase 1, add later if needed

3. **Should we store original audio files permanently?**
   - ✅ **ANSWERED:** Yes, persistent storage with 24h retention policy

4. **Performance impact on high-load scenarios?**
   - Proposal: Measure in E2E tests, optimize if needed
   - ✅ **ANSWERED:** Measure always

## Next Steps

1. Create `tasks.md` with implementation checklist
2. Update affected spec files (if any exist)
3. Run `openspec validate enhance-websocket-message-metadata --strict`
4. Get approval before implementation
