# Frontend Integration Guide - Smart Speech Flow

**Zielgruppe:** Frontend-Entwickler (React/Vue/Angular)
**Version:** 1.0
**Letzte Aktualisierung:** 2025-11-05

## 🎯 Überblick

Dieses Dokument enthält **alles**, was das Frontend braucht, um mit dem Smart Speech Flow Backend zu kommunizieren:

- ✅ API Endpoints für Session-Management
- ✅ WebSocket Integration für Echtzeit-Chat
- ✅ Message Types & Handling
- ✅ Reconnection Pattern
- ✅ Code-Beispiele (Copy & Paste ready)

---

## 📡 API Endpoints

### Base URLs

```javascript
const CONFIG = {
  API_BASE: 'https://ssf.smart-village.solutions',
  WS_BASE: 'wss://ssf.smart-village.solutions',
  // Alternative via Frontend-Proxy:
  WS_ALT: 'wss://translate.smart-village.solutions'
};
```

### 1. Admin: Session erstellen

```javascript
// POST /api/admin/session/create
const response = await fetch(`${CONFIG.API_BASE}/api/admin/session/create`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' }
});

const data = await response.json();
// {
//   "session_id": "ABC12345",
//   "status": "pending",
//   "client_url": "https://ssf.../customer/ABC12345",
//   "qr_code_data": "https://ssf.../customer/ABC12345",
//   "created_at": "2025-11-05T20:00:00Z",
//   "message": "Session ABC12345 erfolgreich erstellt"
// }

const sessionId = data.session_id;
const qrCodeURL = data.qr_code_data; // Für QR-Code Generator
```

### 2. Customer: Session aktivieren

```javascript
// Customer scannt QR-Code → extrahiert session_id aus URL

// Sprachen laden
const langResponse = await fetch(`${CONFIG.API_BASE}/api/customer/languages/supported`);
const languages = await langResponse.json();
// {
//   "languages": {
//     "de": {"name": "Deutsch", "native": "Deutsch"},
//     "en": {"name": "English", "native": "English"},
//     "ar": {"name": "Arabic", "native": "العربية"},
//     ...
//   },
//   "popular": ["en", "ar", "tr", "ru", "fa"]
// }

// Session aktivieren mit gewählter Sprache
const activateResponse = await fetch(
  `${CONFIG.API_BASE}/api/customer/session/activate`,
  {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      customer_language: 'en' // User-Auswahl
    })
  }
);

// Response: 200 OK
// {
//   "session_id": "ABC12345",
//   "status": "active",
//   "customer_language": "en",
//   "message": "Session ABC12345 wurde erfolgreich aktiviert"
// }
```

### 3. Nachricht senden (Text)

```javascript
// POST /api/session/{sessionId}/message
const sendMessage = async (sessionId, text, clientType) => {
  const response = await fetch(
    `${CONFIG.API_BASE}/api/session/${sessionId}/message`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: text,
        source_lang: clientType === 'admin' ? 'de' : 'en',
        target_lang: clientType === 'admin' ? 'en' : 'de',
        client_type: clientType // "admin" oder "customer"
      })
    }
  );

  return await response.json();
  // {
  //   "status": "success",
  //   "message_id": "uuid",
  //   "session_id": "ABC12345",
  //   "original_text": "Hallo",
  //   "translated_text": "Hello",
  //   "audio_available": true,
  //   "audio_url": "/api/audio/uuid.wav",
  //   "processing_time_ms": 1840
  // }
};
```

### 4. Nachricht senden (Audio)

```javascript
const sendAudioMessage = async (sessionId, audioFile, clientType) => {
  const formData = new FormData();
  formData.append('file', audioFile); // WAV, MP3, OGG, FLAC
  formData.append('source_lang', clientType === 'admin' ? 'de' : 'en');
  formData.append('target_lang', clientType === 'admin' ? 'en' : 'de');
  formData.append('client_type', clientType);

  const response = await fetch(
    `${CONFIG.API_BASE}/api/session/${sessionId}/message`,
    {
      method: 'POST',
      body: formData
    }
  );

  return await response.json();
};
```

---

## 🔌 WebSocket Integration

### WebSocket Client (Copy & Paste Ready)

```javascript
class SmartSpeechFlowWebSocket {
  constructor(sessionId, connectionType) {
    this.sessionId = sessionId;
    this.connectionType = connectionType; // "admin" or "customer"
    this.ws = null;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 10;
    this.reconnectDelay = 1000;
    this.isIntentionallyClosed = false;
    this.messageHandlers = {};
    this.onConnectionChange = null;
  }

  connect() {
    const wsUrl = `wss://ssf.smart-village.solutions/ws/${this.sessionId}/${this.connectionType}`;

    console.log(`🔌 Connecting to ${wsUrl}`);
    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      console.log('✅ WebSocket connected');
      this.reconnectAttempts = 0;
      this.reconnectDelay = 1000;
      if (this.onConnectionChange) {
        this.onConnectionChange(true);
      }
    };

    this.ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        this.handleMessage(message);
      } catch (error) {
        console.error('❌ Failed to parse WebSocket message:', error);
      }
    };

    this.ws.onclose = (event) => {
      if (this.isIntentionallyClosed) {
        console.log('👋 WebSocket intentionally closed');
        return;
      }

      console.warn(`⚠️ WebSocket closed (code: ${event.code})`);
      if (this.onConnectionChange) {
        this.onConnectionChange(false);
      }
      this.attemptReconnect();
    };

    this.ws.onerror = (error) => {
      console.error('❌ WebSocket error:', error);
    };
  }

  handleMessage(message) {
    console.log('📨 Received:', message.type);

    switch (message.type) {
      case 'connection_ack':
        console.log('✅ Connection acknowledged:', message.connection_id);
        if (this.messageHandlers.onConnectionAck) {
          this.messageHandlers.onConnectionAck(message);
        }
        break;

      case 'heartbeat':
        // WICHTIG: Pong senden!
        this.sendPong();
        break;

      case 'message':
        // Übersetzte Nachricht → im Chat anzeigen
        if (this.messageHandlers.onMessage) {
          this.messageHandlers.onMessage(message);
        }
        break;

      case 'client_joined':
        // Anderer Teilnehmer verbunden
        console.log(`👤 ${message.client_type} joined`);
        if (this.messageHandlers.onClientJoined) {
          this.messageHandlers.onClientJoined(message);
        }
        break;

      case 'session_terminated':
        console.log('🛑 Session terminated:', message.reason);
        this.isIntentionallyClosed = true;
        if (this.messageHandlers.onSessionTerminated) {
          this.messageHandlers.onSessionTerminated(message);
        }
        this.close();
        break;

      default:
        console.log('📋 Unknown message type:', message.type);
    }
  }

  sendPong() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'pong' }));
    }
  }

  attemptReconnect() {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('❌ Max reconnect attempts reached');
      if (this.messageHandlers.onReconnectFailed) {
        this.messageHandlers.onReconnectFailed();
      }
      return;
    }

    this.reconnectAttempts++;
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000);

    console.log(
      `🔄 Reconnecting... (${this.reconnectAttempts}/${this.maxReconnectAttempts}) in ${this.reconnectDelay}ms`
    );

    setTimeout(() => {
      this.connect();
    }, this.reconnectDelay);
  }

  // Event Handler registrieren
  on(eventType, handler) {
    this.messageHandlers[eventType] = handler;
  }

  close() {
    this.isIntentionallyClosed = true;
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  // Check if connected
  isConnected() {
    return this.ws && this.ws.readyState === WebSocket.OPEN;
  }
}
```

### Usage Example

```javascript
// Admin Frontend
const adminWS = new SmartSpeechFlowWebSocket(sessionId, 'admin');

adminWS.on('onConnectionAck', (msg) => {
  console.log('Connected with ID:', msg.connection_id);
  // Enable chat UI
});

adminWS.on('onMessage', (msg) => {
  // Display message in chat
  displayChatMessage({
    text: msg.text,
    sender: msg.sender,
    timestamp: msg.timestamp,
    audioUrl: msg.audio_url
  });
});

adminWS.on('onClientJoined', (msg) => {
  if (msg.client_type === 'customer') {
    showNotification('Customer joined the session');
  }
});

adminWS.on('onSessionTerminated', (msg) => {
  showNotification('Session ended: ' + msg.reason);
  disableChatUI();
});

adminWS.on('onReconnectFailed', () => {
  alert('Connection lost. Please reload the page.');
});

adminWS.onConnectionChange = (connected) => {
  updateConnectionIndicator(connected);
};

adminWS.connect();

// Cleanup (z.B. React useEffect cleanup)
// return () => adminWS.close();
```

---

## 📨 WebSocket Message Types

### 1. connection_ack (Server → Client)

Bestätigt die WebSocket-Verbindung. Wird **sofort** nach Connect gesendet.

```json
{
  "type": "connection_ack",
  "connection_id": "uuid-1234",
  "session_id": "ABC12345",
  "client_type": "admin",
  "timestamp": "2025-11-05T20:00:00Z"
}
```

**Action:** Chat-UI aktivieren

---

### 2. heartbeat (Server → Client, alle 30s)

Server prüft ob Client noch lebt.

```json
{
  "type": "heartbeat",
  "timestamp": "2025-11-05T20:00:30Z"
}
```

**Action:** **WICHTIG!** Pong senden:
```javascript
ws.send(JSON.stringify({ type: 'pong' }));
```

**Fehlt der Pong:** Server schließt Verbindung nach 60s!

---

### 3. message (Server → Client)

Übersetzte Nachricht von anderem Teilnehmer.

```json
{
  "type": "message",
  "message_id": "uuid-5678",
  "session_id": "ABC12345",
  "text": "Hello, how can I help you?",
  "source_lang": "de",
  "target_lang": "en",
  "sender": "admin",
  "timestamp": "2025-11-05T20:01:00Z",
  "audio_available": true,
  "audio_url": "/api/audio/uuid-5678.wav",
  "role": "receiver_message"
}
```

**Fields:**
- `text`: Übersetzter Text (für dich bestimmt)
- `sender`: Wer hat die Original-Nachricht gesendet (`admin` oder `customer`)
- `role`:
  - `receiver_message`: Du empfängst die Übersetzung
  - `sender_message`: Bestätigung deiner eigenen Nachricht
- `audio_available`: Wenn `true`, kann Audio abgespielt werden
- `audio_url`: URL zum Audio-File (GET Request, kein Auth nötig)

**Action:** Nachricht im Chat anzeigen

---

### 4. client_joined (Server → Client)

Anderer Teilnehmer hat sich verbunden.

```json
{
  "type": "client_joined",
  "session_id": "ABC12345",
  "client_type": "customer",
  "connection_id": "uuid-9999",
  "timestamp": "2025-11-05T20:00:15Z"
}
```

**Action:** Benachrichtigung anzeigen ("Customer joined")

---

### 5. session_terminated (Server → Client)

Session wurde beendet.

```json
{
  "type": "session_terminated",
  "session_id": "ABC12345",
  "reason": "admin_ended",
  "timestamp": "2025-11-05T20:10:00Z"
}
```

**Possible reasons:**
- `admin_ended`: Admin hat Session beendet
- `timeout`: Session-Timeout
- `error`: Server-Fehler

**Action:**
- Chat-UI deaktivieren
- WebSocket schließen (keine Reconnects!)
- Benutzer informieren

---

## 🎨 UI Flow

### Admin Workflow

```
1. [Button: "Neue Session"]
   ↓
   POST /api/admin/session/create
   ↓
   Erhalte: session_id + QR-Code URL
   ↓
2. [QR-Code anzeigen]
   ↓
   Customer scannt QR-Code
   ↓
3. [WebSocket verbinden]
   ws://.../{session_id}/admin
   ↓
   Empfange: connection_ack
   ↓
4. [Warte auf Customer]
   Empfange: client_joined (type=customer)
   ↓
   [Chat aktivieren]
   ↓
5. [Nachrichten senden/empfangen]
   - Eigene Nachricht: POST /api/session/{id}/message
   - Antwort: WebSocket message type="message"
   ↓
6. [Session beenden]
   DELETE /api/admin/session/{id}/terminate
```

### Customer Workflow

```
1. [QR-Code scannen]
   ↓
   URL: https://ssf.../customer/ABC12345
   Extrahiere: session_id
   ↓
2. [Sprache wählen]
   GET /api/customer/languages/supported
   ↓
   Zeige: Sprachauswahl (de, en, ar, tr, ...)
   ↓
3. [Session aktivieren]
   POST /api/customer/session/activate
   {session_id, customer_language}
   ↓
4. [WebSocket verbinden]
   ws://.../{session_id}/customer
   ↓
   Empfange: connection_ack
   ↓
   [Chat aktivieren]
   ↓
5. [Nachrichten senden/empfangen]
   (gleich wie Admin)
```

---

## 🚨 Häufige Fehler & Lösungen

### ❌ Fehler 1: Kein Heartbeat-Pong

**Symptom:** WebSocket schließt nach 60 Sekunden

**Ursache:**
```javascript
case 'heartbeat':
  break; // ❌ Nichts tun
```

**Lösung:**
```javascript
case 'heartbeat':
  this.ws.send(JSON.stringify({ type: 'pong' })); // ✅
  break;
```

---

### ❌ Fehler 2: Kein Reconnect

**Symptom:** Bei Netzwerk-Problemen funktioniert Chat nicht mehr

**Ursache:**
```javascript
ws.onclose = () => {
  console.log('Disconnected'); // ❌ Nichts tun
};
```

**Lösung:**
```javascript
ws.onclose = () => {
  this.attemptReconnect(); // ✅
};
```

---

### ❌ Fehler 3: Falscher Connection Type

**Symptom:** WebSocket schließt sofort oder 403 Forbidden

**Ursache:**
```javascript
// ❌ Falsch
ws://server/ws/ABC123/client
ws://server/ws/ABC123/user
```

**Lösung:**
```javascript
// ✅ Korrekt
ws://server/ws/ABC123/admin
ws://server/ws/ABC123/customer
```

---

### ❌ Fehler 4: Session nicht aktiviert

**Symptom:** Customer kann keine Nachrichten senden (400 Bad Request)

**Ursache:** `/api/customer/session/activate` wurde nicht aufgerufen

**Lösung:**
```javascript
// Customer MUSS Session aktivieren bevor Chat möglich ist
await fetch('/api/customer/session/activate', {
  method: 'POST',
  body: JSON.stringify({
    session_id: sessionId,
    customer_language: 'en'
  })
});
```

---

## 🧪 Testing

### Test 1: WebSocket Verbindung

```javascript
const ws = new WebSocket('wss://ssf.smart-village.solutions/ws/TEST123/admin');

ws.onopen = () => console.log('✅ Connected');
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  console.log('📨', msg.type, msg);

  if (msg.type === 'heartbeat') {
    ws.send(JSON.stringify({ type: 'pong' }));
    console.log('💓 Pong sent');
  }
};
ws.onerror = (e) => console.error('❌', e);
ws.onclose = () => console.log('👋 Closed');
```

### Test 2: Nachricht senden

```javascript
const response = await fetch('https://ssf.smart-village.solutions/api/session/TEST123/message', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    text: 'Test Nachricht',
    source_lang: 'de',
    target_lang: 'en',
    client_type: 'admin'
  })
});

console.log(await response.json());
```

### Test 3: Session erstellen & aktivieren

```javascript
// Admin: Session erstellen
const createResp = await fetch('https://ssf.smart-village.solutions/api/admin/session/create', {
  method: 'POST'
});
const session = await createResp.json();
console.log('Session ID:', session.session_id);

// Customer: Session aktivieren
const activateResp = await fetch('https://ssf.smart-village.solutions/api/customer/session/activate', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    session_id: session.session_id,
    customer_language: 'en'
  })
});
console.log('Activated:', await activateResp.json());
```

---

## 📱 React Integration Beispiel

```jsx
import { useEffect, useState, useRef } from 'react';

function Chat({ sessionId, userType }) {
  const [messages, setMessages] = useState([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);

  useEffect(() => {
    // WebSocket initialisieren
    const ws = new SmartSpeechFlowWebSocket(sessionId, userType);

    ws.on('onConnectionAck', () => {
      setConnected(true);
    });

    ws.on('onMessage', (msg) => {
      setMessages(prev => [...prev, {
        text: msg.text,
        sender: msg.sender,
        timestamp: msg.timestamp,
        audioUrl: msg.audio_url
      }]);
    });

    ws.on('onReconnectFailed', () => {
      alert('Verbindung verloren. Bitte Seite neu laden.');
    });

    ws.onConnectionChange = (isConnected) => {
      setConnected(isConnected);
    };

    ws.connect();
    wsRef.current = ws;

    // Cleanup
    return () => {
      ws.close();
    };
  }, [sessionId, userType]);

  const sendMessage = async (text) => {
    const response = await fetch(`/api/session/${sessionId}/message`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        source_lang: userType === 'admin' ? 'de' : 'en',
        target_lang: userType === 'admin' ? 'en' : 'de',
        client_type: userType
      })
    });

    return response.json();
  };

  return (
    <div>
      <div className={`status ${connected ? 'connected' : 'disconnected'}`}>
        {connected ? '🟢 Verbunden' : '🔴 Getrennt'}
      </div>

      <div className="messages">
        {messages.map((msg, i) => (
          <div key={i} className={`message ${msg.sender}`}>
            <p>{msg.text}</p>
            {msg.audioUrl && (
              <audio controls src={msg.audioUrl} />
            )}
          </div>
        ))}
      </div>

      <input
        type="text"
        onKeyPress={(e) => {
          if (e.key === 'Enter' && e.target.value) {
            sendMessage(e.target.value);
            e.target.value = '';
          }
        }}
        disabled={!connected}
        placeholder={connected ? 'Nachricht eingeben...' : 'Verbindung wird hergestellt...'}
      />
    </div>
  );
}
```

---

## ✅ Checkliste vor Production

- [ ] WebSocket-Client mit Reconnection implementiert
- [ ] Heartbeat-Pong wird korrekt gesendet (alle 30s)
- [ ] Alle Message Types werden behandelt (connection_ack, heartbeat, message, client_joined, session_terminated)
- [ ] Audio-Player für `audio_url` integriert
- [ ] Session-Aktivierung für Customer implementiert
- [ ] QR-Code Generator für Admin (nutze `qr_code_data` aus API)
- [ ] Error Handling für API-Fehler (400, 404, 500)
- [ ] UI zeigt Verbindungsstatus an (🟢/🔴)
- [ ] Reconnection-Hinweis für User
- [ ] Getestet mit echten Sessions (nicht nur Mocks)
- [ ] Network-Disconnect-Szenario getestet
- [ ] Container-Restart-Szenario getestet (reconnect funktioniert?)

---

## 📚 Weitere Dokumentation

**Backend Docs:**
- `docs/frontend_api.md` - Vollständige API-Referenz
- `docs/customer-api.md` - Customer-spezifische Endpoints
- `docs/deployment-websocket-reconnection.md` - Detailliertes Reconnection-Pattern

**Wichtige URLs:**
- API: `https://ssf.smart-village.solutions`
- WebSocket: `wss://ssf.smart-village.solutions`
- Prometheus: `http://prometheus-ssf.smart-village.solutions`
- Grafana: `http://grafana-ssf.smart-village.solutions`

---

## 🆘 Support

**Bei Problemen:**

1. **Browser Console checken** - Alle WebSocket Messages werden geloggt
2. **Network Tab checken** - WebSocket Connection Status prüfen
3. **Backend Logs** - `docker compose logs api_gateway --tail 100`
4. **Prometheus Metrics** - `websocket_broadcast_failure_total` prüfen

**Häufigste Probleme:**
- ❌ **"WebSocket closes immediately"** → Falscher `connectionType` (muss "admin" oder "customer" sein)
- ❌ **"Messages not arriving"** → Kein Heartbeat-Pong gesendet
- ❌ **"Can't send messages"** → Session nicht aktiviert (Customer) oder Status nicht "active"
- ❌ **"Reconnect doesn't work"** → `onclose` Handler fehlt oder `isIntentionallyClosed` nicht gesetzt

**Kontakt:**
- Backend Team: #backend-incidents (Slack)
- Dokumentation: Siehe `docs/` Ordner im Repository

---

**Version:** 1.0 | **Stand:** 2025-11-05 | **WebSocket Broadcasting: 100% funktionsfähig** ✅
