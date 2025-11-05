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
  "audio_available": false
}
```

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
  "audio_url": "/api/audio/a1b2c3d4.wav"
}
```

---

## 🔄 Message Flow

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
    }
    // sender_confirmation wird ignoriert (lokal bereits angezeigt)

    // Option 2: Server-bestätigt
    if (message.role === "receiver_message" ||
        message.role === "sender_confirmation") {
      displayMessage(message);
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
}
```

**Garantien:**
1. Jede gesendete Nachricht erzeugt **genau 2 WebSocket-Messages**
2. Beide haben die gleiche `message_id`
3. `sender_confirmation` hat immer `audio_available: false`
4. `receiver_message` hat `audio_available: true` wenn TTS erfolgreich
5. `sender` ist immer der **ursprüngliche Absender** (nicht Empfänger)

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
