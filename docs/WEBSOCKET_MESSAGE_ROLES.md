# WebSocket Message Roles - Backend Dokumentation

**Datum:** 2025-11-05
**Version:** 1.0
**Status:** Production

---

## 📋 Übersicht

Das Backend sendet **zwei verschiedene WebSocket-Nachrichten** für jede gesendete Message:

1. **Sender Confirmation** → An den Absender (Echo)
2. **Receiver Message** → An den Empfänger (Übersetzung + Audio)

Dies ermöglicht differenzierte Inhalte für beide Clients.

---

## 🔧 Implementation

### Code Location
**Datei:** `/services/api_gateway/routes/session.py`
**Funktion:** `broadcast_message_to_session()` (Zeile 571-630)

### Message-Konstruktion

```python
# 1. Original Message für Sender (ASR-Bestätigung)
sender_message = {
    "type": MessageType.MESSAGE.value,
    "message_id": message.id,
    "session_id": session_id,
    "text": message.original_text,  # Original-Sprache
    "source_lang": message.source_lang,
    "target_lang": message.target_lang,
    "sender": message.sender.value,  # "admin" oder "customer"
    "timestamp": message.timestamp.isoformat(),
    "audio_available": False,  # Sender braucht kein Audio
    "role": "sender_confirmation",  # Identifiziert als Echo
}

# 2. Translated Message für Empfänger (mit Audio)
receiver_message = {
    "type": MessageType.MESSAGE.value,
    "message_id": message.id,
    "session_id": session_id,
    "text": message.translated_text,  # Ziel-Sprache
    "source_lang": message.source_lang,
    "target_lang": message.target_lang,
    "sender": message.sender.value,
    "timestamp": message.timestamp.isoformat(),
    "audio_available": message.audio_base64 is not None,
    "audio_url": f"/api/audio/{message.id}.wav" if message.audio_base64 else None,
    "role": "receiver_message",  # Identifiziert als neue Nachricht
}
```

### Broadcasting Logic

```python
# Differentiated Broadcasting
result = await manager.broadcast_with_differentiated_content(
    session_id=session_id,
    sender_type=sender_type,
    original_message=sender_message,    # → An Sender
    translated_message=receiver_message, # → An Empfänger
)
```

**Implementation:** `/services/api_gateway/websocket.py` Zeile 550-660

---

## 📊 Message Roles

### `role: "sender_confirmation"`

**Zweck:** Bestätigung an Absender dass Nachricht empfangen wurde
**Empfänger:** Der Client der die Nachricht gesendet hat
**Inhalt:**
- Original-Text (nicht übersetzt)
- Kein Audio (Sender kennt bereits den Inhalt)
- Gleiche `message_id` wie `receiver_message`

**Frontend-Verhalten:**
- Kann ignoriert werden wenn Frontend optimistische UI-Updates nutzt
- Kann für Bestätigung/Synchronisation verwendet werden
- Ist **redundant** wenn Frontend bereits lokal anzeigt

**Beispiel:**
```json
{
  "type": "message",
  "role": "sender_confirmation",
  "sender": "admin",
  "text": "Hallo, wie kann ich helfen?",
  "audio_available": false,
  "pipeline_metadata": {
    "input": {
      "type": "audio",
      "source_lang": "de"
    },
    "steps": [
      {
        "name": "asr",
        "started_at": "2025-11-05T12:00:00.000Z",
        "completed_at": "2025-11-05T12:00:00.150Z",
        "duration_ms": 150,
        "input": {},
        "output": {
          "text": "Hallo, wie kann ich helfen?"
        }
      },
      {
        "name": "translation",
        "started_at": "2025-11-05T12:00:00.150Z",
        "completed_at": "2025-11-05T12:00:00.300Z",
        "duration_ms": 150,
        "input": {},
        "output": {
          "text": "مرحبا، كيف يمكنني المساعدة؟",
          "model": "m2m100_1.2B"
        }
      },
      {
        "name": "tts",
        "started_at": "2025-11-05T12:00:00.300Z",
        "completed_at": "2025-11-05T12:00:00.500Z",
        "duration_ms": 200,
        "input": {},
        "output": {
          "audio_format": "wav",
          "sample_rate": 22050
        }
      }
    ],
    "total_duration_ms": 500,
    "pipeline_started_at": "2025-11-05T12:00:00.000Z",
    "pipeline_completed_at": "2025-11-05T12:00:00.500Z"
  }
}
```

**WICHTIG:** Das `pipeline_metadata` Feld ist **IMMER vorhanden** in allen WebSocket-Nachrichten, unabhängig von der Rolle. Es enthält detaillierte Informationen über jeden Schritt der Verarbeitungspipeline (ASR, Translation, TTS).

---

### `role: "receiver_message"`

**Zweck:** Neue Nachricht an Empfänger
**Empfänger:** Der andere Client (nicht der Absender)
**Inhalt:**
- Übersetzter Text (Ziel-Sprache)
- Audio-Datei (TTS-generiert)
- Vollständige Message-Metadaten

**Frontend-Verhalten:**
- **MUSS** angezeigt werden
- Enthält alle Informationen für Chat-Darstellung
- Audio kann abgespielt werden

**Beispiel:**
```json
{
  "type": "message",
  "role": "receiver_message",
  "sender": "admin",
  "text": "مرحبا، كيف يمكنني المساعدة؟",
  "audio_available": true,
  "audio_url": "/api/audio/a1b2c3d4.wav",
  "original_audio_url": "/api/audio/input_a1b2c3d4.wav",
  "pipeline_metadata": {
    "input": {
      "type": "audio",
      "source_lang": "de",
      "audio_url": "/api/audio/input_a1b2c3d4.wav"
    },
    "steps": [
      {
        "name": "asr",
        "started_at": "2025-11-05T12:00:00.000Z",
        "completed_at": "2025-11-05T12:00:00.150Z",
        "duration_ms": 150,
        "input": {},
        "output": {
          "text": "Hallo, wie kann ich helfen?"
        }
      },
      {
        "name": "translation",
        "started_at": "2025-11-05T12:00:00.150Z",
        "completed_at": "2025-11-05T12:00:00.300Z",
        "duration_ms": 150,
        "input": {},
        "output": {
          "text": "مرحبا، كيف يمكنني المساعدة؟",
          "model": "m2m100_1.2B"
        }
      },
      {
        "name": "tts",
        "started_at": "2025-11-05T12:00:00.300Z",
        "completed_at": "2025-11-05T12:00:00.500Z",
        "duration_ms": 200,
        "input": {},
        "output": {
          "audio_format": "wav",
          "sample_rate": 22050
        }
      }
    ],
    "total_duration_ms": 500,
    "pipeline_started_at": "2025-11-05T12:00:00.000Z",
    "pipeline_completed_at": "2025-11-05T12:00:00.500Z"
  }
}
```

**WICHTIG:**
- Das `pipeline_metadata` Feld ist **IMMER vorhanden** in allen WebSocket-Nachrichten
- Bei Audio-Input enthält `pipeline_metadata.input.audio_url` die URL zur Original-Audiodatei
- Das zusätzliche Feld `original_audio_url` auf Top-Level bietet direkten Zugriff auf die Original-Audiodatei (nur bei Audio-Input, ansonsten `null`)
- Bei Text-Input ist `pipeline_metadata.input.type` auf `"text"` gesetzt und `original_audio_url` ist `null`

---

## � Pipeline Metadata

### Übersicht

**Seit Version 1.1** enthalten ALLE WebSocket-Nachrichten ein `pipeline_metadata` Feld mit detaillierten Informationen über die Verarbeitungspipeline.

### Struktur

Das `pipeline_metadata` Objekt enthält:

1. **Input Information**: Typ (audio/text), Sprache, optional Audio-URL
2. **Pipeline Steps**: Array mit allen Verarbeitungsschritten
3. **Timing Information**: Gesamt-Dauer und Zeitstempel

### Verfügbare Pipeline-Schritte

| Step Name | Beschreibung | Input Type | Output |
|-----------|--------------|------------|--------|
| `asr` | Automatic Speech Recognition | Audio | Text |
| `translation` | Text-Übersetzung | Text | Übersetzter Text |
| `tts` | Text-to-Speech | Text | Audio |
| `refinement` | Optional: LLM-basierte Verbesserung | Text | Verbesserter Text |

### Timing-Felder

Alle Zeitstempel sind im **ISO 8601 Format** mit Millisekunden-Präzision:

```typescript
{
  "started_at": "2025-11-05T12:00:00.000Z",
  "completed_at": "2025-11-05T12:00:00.150Z",
  "duration_ms": 150
}
```

### Original Audio URL

Bei Audio-Input enthält die Nachricht zusätzlich:

- `original_audio_url`: Top-Level-Feld für direkten Zugriff
- `pipeline_metadata.input.audio_url`: Redundant, aber innerhalb der Metadaten

Die Original-Audiodatei wird für **24 Stunden** gespeichert und kann über die URL abgerufen werden.

### Verwendungszwecke

**Frontend:**
- Performance-Monitoring (Pipeline-Dauer anzeigen)
- Debugging (Welcher Schritt dauerte am längsten?)
- Original-Audio-Playback ermöglichen
- Qualitäts-Metriken sammeln

**Beispiel - Performance anzeigen:**
```typescript
function displayPipelinePerformance(metadata: PipelineMetadata) {
  const totalMs = metadata.total_duration_ms;
  console.log(`Total processing time: ${totalMs}ms`);

  metadata.steps.forEach(step => {
    const percentage = (step.duration_ms / totalMs * 100).toFixed(1);
    console.log(`  ${step.name}: ${step.duration_ms}ms (${percentage}%)`);
  });
}
```

### Backward Compatibility

**Wichtig:** Das `pipeline_metadata` Feld ist **optional für alte Clients**.

Alte Frontend-Versionen können das Feld ignorieren ohne Fehler zu verursachen. Neue Clients sollten jedoch prüfen, ob das Feld vorhanden ist, bevor sie darauf zugreifen:

```typescript
if (message.pipeline_metadata) {
  // Use metadata
} else {
  // Fallback für alte Nachrichten
}
```

---

## �🔄 Message Flow

### Beispiel: Admin sendet Nachricht (de → ar)

```
┌─────────────┐
│ Admin (de)  │ → POST /api/session/ABC123/message
└─────────────┘   { text: "Hallo", source_lang: "de", target_lang: "ar" }
       ↓
┌─────────────────────────────────────────┐
│ Backend Pipeline                        │
│ 1. Text validieren                      │
│ 2. Translation Service (de → ar)        │
│ 3. TTS Service (ar → audio)             │
│ 4. SessionMessage erstellen             │
└─────────────────────────────────────────┘
       ↓
┌─────────────────────────────────────────┐
│ WebSocket Broadcasting                  │
└─────────────────────────────────────────┘
       ├─────────────────────┬─────────────────────┐
       ↓                     ↓                     ↓
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│ Admin WS    │      │ Customer WS │      │ (andere)    │
│ (Sender)    │      │ (Empfänger) │      │             │
└─────────────┘      └─────────────┘      └─────────────┘
   ↓                     ↓
   │ sender_confirmation │ receiver_message
   │ text: "Hallo"       │ text: "مرحبا"
   │ audio: false        │ audio: true
   │                     │ audio_url: "..."
```

---

## 🎯 Frontend Integration

### Empfohlene Logik

```typescript
websocket.onmessage = (event) => {
  const message = JSON.parse(event.data);

  if (message.type === "message") {

    // Option 1: Optimistic Updates (empfohlen)
    if (message.role === "receiver_message") {
      // Nur Nachrichten vom anderen Client anzeigen
      displayMessage(message);

      // Pipeline-Metadaten für Debugging/Monitoring
      if (message.pipeline_metadata) {
        console.log('Pipeline total duration:', message.pipeline_metadata.total_duration_ms, 'ms');
        message.pipeline_metadata.steps.forEach(step => {
          console.log(`  ${step.name}: ${step.duration_ms}ms`);
        });
      }

      // Original-Audio für Debugging/Playback
      if (message.original_audio_url) {
        console.log('Original audio available at:', message.original_audio_url);
      }
    }
    // sender_confirmation wird ignoriert (lokal bereits angezeigt)

    // Option 2: Server-bestätigt
    if (message.role === "receiver_message" ||
        message.role === "sender_confirmation") {
      displayMessage(message);

      // Pipeline-Metadaten sind immer verfügbar
      trackPerformanceMetrics(message.pipeline_metadata);
    }
  }
};
```

### Beide Ansätze funktionieren

**Optimistic Updates (Frontend aktuell):**
- ✅ Schnellere UX (keine Latenz)
- ✅ Einfachere Logik
- ⚠️ Muss Fehler manuell behandeln

**Server-bestätigt:**
- ✅ Garantierte Synchronisation
- ✅ Automatische Fehlerbehandlung
- ⚠️ Langsamere UX (Netzwerk-Latenz)

---

## 📝 API Contract

### WebSocket Message Type: `"message"`

**Schema:**
```typescript
interface PipelineStep {
  name: "asr" | "translation" | "tts" | "refinement";
  started_at: string;        // ISO 8601 timestamp
  completed_at: string;      // ISO 8601 timestamp
  duration_ms: number;       // Duration in milliseconds
  input: Record<string, any>; // Step-specific input data
  output: Record<string, any>; // Step-specific output data
}

interface PipelineMetadata {
  input: {
    type: "audio" | "text";
    source_lang: string;     // ISO 639-1 code
    audio_url?: string;      // Only for audio input
  };
  steps: PipelineStep[];
  total_duration_ms: number;
  pipeline_started_at: string; // ISO 8601 timestamp
  pipeline_completed_at: string; // ISO 8601 timestamp
}

interface ChatMessage {
  type: "message";
  role: "sender_confirmation" | "receiver_message";
  message_id: string;        // UUIDv4
  session_id: string;        // Session identifier
  text: string;              // Message content (original or translated)
  sender: "admin" | "customer";
  timestamp: string;         // ISO 8601 format
  source_lang: string;       // ISO 639-1 code (e.g. "de", "ar")
  target_lang: string;       // ISO 639-1 code
  audio_available: boolean;
  audio_url?: string;        // Optional, nur bei receiver_message
  original_audio_url?: string | null; // URL to original input audio (nur bei Audio-Input)
  pipeline_metadata: PipelineMetadata; // ALWAYS present
}
```

**Garantien:**
1. Jede gesendete Nachricht erzeugt **genau 2 WebSocket-Messages**
2. Beide haben die gleiche `message_id`
3. `sender_confirmation` hat immer `audio_available: false`
4. `receiver_message` hat `audio_available: true` wenn TTS erfolgreich
5. `sender` ist immer der **ursprüngliche Absender** (nicht Empfänger)
6. **NEU:** `pipeline_metadata` ist **IMMER vorhanden** in allen WebSocket-Nachrichten
7. **NEU:** `original_audio_url` ist vorhanden bei Audio-Input, ansonsten `null`

---

## 🔍 Debugging

### Backend-Logs prüfen

```bash
# WebSocket Broadcasting-Logs
docker compose logs api_gateway | grep "Broadcasting"

# Erwartete Ausgabe:
# 📡 Broadcasting message in session ABC123 from admin
# 📤 Broadcasting differentiated content to session ABC123
# ✅ Broadcast completed: 2/2 delivered
```

### WebSocket-Traffic prüfen

**Browser DevTools → Network → WS → Messages:**

Für jede gesendete Nachricht sollten **2 Messages** ankommen:
```
↓ { "type": "message", "role": "sender_confirmation", ... }
↓ { "type": "message", "role": "receiver_message", ... }
```

---

## ⚠️ Wichtige Hinweise

### 1. Role-Namen ändern?

**NICHT EMPFOHLEN** ohne Frontend-Abstimmung!

Aktuell: `"sender_confirmation"`
Alternative: `"sender_message"` (wie ursprünglich geplant)

**Wenn Änderung gewünscht:**
1. Beide Teams abstimmen
2. Versionierung einführen
3. Graceful Migration planen

### 2. Audio bei sender_confirmation?

**Aktuell:** Bewusst `audio_available: false`

**Grund:** Sender kennt bereits den Inhalt, braucht kein Audio von sich selbst

**Wenn gewünscht:** Kann hinzugefügt werden, erhöht aber Traffic

### 3. Message-ID Konsistenz

**Wichtig:** Beide Messages (sender + receiver) verwenden die **gleiche `message_id`**

Frontend kann darüber Duplikate erkennen oder Messages matchen.

---

## 🚀 Performance

### Metriken

- **Broadcast-Latenz:** < 50ms (typisch)
- **Messages pro Request:** Exakt 2
- **Erfolgsrate:** > 99.9% (bei stabiler WebSocket-Verbindung)

### Monitoring

```python
# Prometheus Metrics
websocket_broadcast_total{session_id, sender_type}
websocket_broadcast_success_total{session_id, sender_type}
websocket_broadcast_failure_total{session_id, sender_type, reason}
websocket_broadcast_messages_delivered{session_id, sender_type}
```

---

## 📚 Verwandte Dokumentation

- `/docs/frontend_api.md` → API-Endpunkte
- `/docs/FRONTEND_MESSAGE_HANDLING_FIX.md` → Frontend-Integration
- `/docs/session_flow.md` → Session-Lebenszyklus
- `/services/api_gateway/websocket.py` → WebSocket-Implementation

---

**Version:** 1.0
**Letzte Änderung:** 2025-11-05
**Autor:** Backend-Team
**Review:** Frontend-Team ✅
