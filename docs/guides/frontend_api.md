# Frontend API Leitfaden

Dieser Leitfaden beschreibt die relevanten öffentlichen Endpunkte, damit das Frontend Admin-initiierte Gespräche startet, Kund*innen über Deeplink beitreten lässt, Spracheingaben entgegennimmt und Antworten als Text sowie Audio ausgibt. Alle Beispiele verwenden die produktive Basis-URL

```
https://translate.smart-village.solutions
```

## 1. Admin startet neues Gespräch

| Zweck | Methode & Pfad | Hinweise |
|-------|----------------|----------|
| Neue Session erzeugen | `POST /api/admin/session/create` | Liefert `session_id`, `client_url`, `status`, `created_at`, `message`. Das Frontend sollte die `session_id` für den Deeplink nutzen. |
| Aktuelle Session anzeigen | `GET /api/admin/session/current` | Gibt Status der aktiven Session zurück (`status`, `customer_language`, `admin_connected`, `customer_connected`, `message_count`). Bei 404 existiert keine aktive Session. |
| Sessionhistorie anzeigen | `GET /api/admin/session/history?limit=10` | Liefert letzte beendete Sessions plus optional aktive Session. |
| Session terminieren | `DELETE /api/admin/session/{sessionId}/terminate` | Beendet die Session inkl. WebSocket-Benachrichtigung. |

## 2. Kunde betritt Session via Deeplink

1. **Session validieren** – `GET /api/session/{sessionId}`
   - Antwort enthält `status`, `customer_language`, `admin_language`, `message_count`, Flags für verbundene Teilnehmer.
   - Falls 404 zurückkommt, ist die Session ungültig oder bereits beendet.

2. **Sprachauswahl anzeigen** – `GET /api/languages/supported`
   - Antwort liefert `languages` (Key–Value-Map), `admin_default` und `popular` Sprachen.
   - Kund*innen wählen ihre Sprache (`customer_language`).

3. **Session aktivieren** – `POST /api/customer/session/activate`
   ```json
   {
     "session_id": "ABC12345",
     "customer_language": "de"
   }
   ```
   - Überführt die Session vom `pending` in den `active` Status.
   - Nach erfolgreicher Aktivierung können Nachrichten gesendet werden.

4. **Session-Status prüfen** – `GET /api/customer/session/{sessionId}/status`
   - Liefert Customer-spezifischen Session-Status (`can_send_messages`, `is_active`, etc.).
   - Kann für UI-Updates verwendet werden.

> **Hinweis:** Die Session muss explizit über `/api/customer/session/activate` aktiviert werden, bevor Nachrichten gesendet werden können. Die gewählten Sprachen werden bei jeder Nachricht im jeweiligen Request angegeben und so an die Pipeline übergeben.

## 3. Nachrichten senden

### 3.1 Textnachricht

```
POST /api/session/{sessionId}/message
Content-Type: application/json

{
  "text": "Guten Tag",
  "source_lang": "de",
  "target_lang": "en",
  "client_type": "customer"
}
```

- Pflichtfelder: `text`, `source_lang`, `target_lang`, `client_type`
- `client_type`: Rolle des Senders - `admin` (deutschsprachiger Mitarbeiter) oder `customer` (mehrsprachiger Kunde/Bürger)
- Erfolgsresponse:

```json
{
  "status": "success",
  "message_id": "c3f3d9b8-...",
  "session_id": "AB12CD34",
  "original_text": "Guten Tag",
  "translated_text": "Good day",
  "audio_available": true,
  "audio_url": "/api/audio/c3f3d9b8-....wav",
  "processing_time_ms": 1840,
  "pipeline_type": "text",
  "source_lang": "de",
  "target_lang": "en",
  "timestamp": "2025-11-02T11:32:05.418216",
  "pipeline_metadata": {
    "input": {
      "type": "text",
      "source_lang": "de"
    },
    "steps": [
      {
        "name": "translation",
        "started_at": "2025-11-02T11:32:05.100Z",
        "completed_at": "2025-11-02T11:32:05.850Z",
        "duration_ms": 750,
        "input": {
          "text": "Guten Tag",
          "source_lang": "de",
          "target_lang": "en",
          "model": "m2m100_1.2B"
        },
        "output": {
          "text": "Good day",
          "model": "m2m100_1.2B"
        }
      },
      {
        "name": "tts",
        "started_at": "2025-11-02T11:32:05.850Z",
        "completed_at": "2025-11-02T11:32:06.940Z",
        "duration_ms": 1090,
        "input": {
          "text": "Good day",
          "target_lang": "en",
          "model": "coqui-tts"
        },
        "output": {}
      }
    ],
    "total_duration_ms": 1840,
    "pipeline_started_at": "2025-11-02T11:32:05.100Z",
    "pipeline_completed_at": "2025-11-02T11:32:06.940Z"
  }
}
```

> **Neu:** Das `pipeline_metadata`-Feld enthält detaillierte Informationen über jeden Verarbeitungsschritt (ASR, Translation, TTS) mit Timestamps, Modellen und Ein-/Ausgaben. Siehe Abschnitt 7 für Details.

### 3.2 Sprachnachricht

```
POST /api/session/{sessionId}/message
Content-Type: multipart/form-data

file=<WAV/MP3/...>
source_lang=de
target_lang=en
client_type=customer
```

- Das Datei-Feld muss `file` heißen.
- Unterstützte Audioformate werden serverseitig automatisch in das benötigte WAV-Format konvertiert.
- Response entspricht dem Textfall, `pipeline_type` ist `audio` und `original_text` enthält das ASR-Ergebnis zur Kontrolle.
- `client_type`: Rolle des Senders - `admin` (Mitarbeiter) oder `customer` (Kunde/Bürger)

## 4. Antworten konsumieren

### 4.1 Audio abrufen

- Wenn `audio_available` true ist, kann der Browser die **übersetzte** Audioausgabe über
  `GET /api/audio/{message_id}.wav`
  abspielen oder herunterladen.

- Bei Sprachnachrichten (Audio-Input) ist auch die **Original-Audioaufnahme** verfügbar:
  `GET /api/audio/input_{message_id}.wav`

  > **Hinweis:** Original-Audiodateien werden aus Datenschutzgründen nach **24 Stunden automatisch gelöscht**. Danach gibt der Endpunkt 404 zurück. Die URL ist im `pipeline_metadata.input.audio_url` verfügbar.

### 4.2 Verlauf & Status aktualisieren

- `GET /api/session/{sessionId}/messages` liefert die komplette Nachrichtenliste (`original_text`, `translated_text`, `audio_base64`, `timestamp`).
- `GET /api/session/{sessionId}` kann für allgemeine Statusprüfungen genutzt werden.
- `GET /api/customer/session/{sessionId}/status` für Customer-spezifische Statusprüfungen (empfohlen für Kunden-Frontend).
- `GET /api/admin/session/current` für Admin-spezifische Statusprüfungen (empfohlen für Admin-Frontend).

### 4.3 Activity-Updates (optional)

```
POST /api/session/{sessionId}/activity
Content-Type: application/json

{
  "is_mobile": true,
  "tab_active": false,
  "battery_level": 0.25,
  "network_quality": "slow"
}
```

- Dient zur Optimierung der Update-Frequenz (Polling/Push). Antwort enthält einen vorgeschlagenen neuen Polling-Intervall und Tipps zur Akkuoptimierung. Nutzung optional.

## 5. Echtzeitkommunikation per WebSocket

- Verbindungs-URL: `wss://ssf.smart-village.solutions/ws/{sessionId}/{clientType}` (empfohlen) oder `wss://translate.smart-village.solutions/ws/{sessionId}/{clientType}` (via Frontend-Reverse-Proxy)
  - `clientType` = `admin` oder `customer`.
  - Bei ungültiger Session oder falschem Typ schließt der Server die Verbindung.

- Eingehende Nachrichten tragen die Form:

```json
{
  "type": "message",
  "message_id": "...",
  "session_id": "...",
  "text": "Hello",
  "source_lang": "en",
  "target_lang": "de",
  "sender": "admin",
  "timestamp": "...",
  "audio_available": true,
  "audio_url": "/api/audio/...",
  "role": "receiver_message",
  "pipeline_metadata": {
    "input": {
      "type": "audio",
      "audio_url": "/api/audio/input_....wav",
      "source_lang": "en"
    },
    "steps": [
      {
        "name": "asr",
        "started_at": "2025-11-02T11:32:05.000Z",
        "completed_at": "2025-11-02T11:32:06.200Z",
        "duration_ms": 1200,
        "input": {},
        "output": {
          "text": "Hello"
        }
      },
      {
        "name": "translation",
        "started_at": "2025-11-02T11:32:06.200Z",
        "completed_at": "2025-11-02T11:32:07.000Z",
        "duration_ms": 800,
        "input": {
          "text": "Hello",
          "source_lang": "en",
          "target_lang": "de",
          "model": "m2m100_1.2B"
        },
        "output": {
          "text": "Hallo",
          "model": "m2m100_1.2B"
        }
      },
      {
        "name": "tts",
        "started_at": "2025-11-02T11:32:07.000Z",
        "completed_at": "2025-11-02T11:32:07.500Z",
        "duration_ms": 500,
        "input": {
          "text": "Hallo",
          "target_lang": "de",
          "model": "coqui-tts"
        },
        "output": {}
      }
    ],
    "total_duration_ms": 2500,
    "pipeline_started_at": "2025-11-02T11:32:05.000Z",
    "pipeline_completed_at": "2025-11-02T11:32:07.500Z"
  }
}
```

> **Neu:** WebSocket-Nachrichten enthalten jetzt immer `pipeline_metadata` mit detaillierten Performance- und Verarbeitungsinformationen. Siehe Abschnitt 7 für Details.

### 5.1 WebSocket Message Roles

Das Backend sendet **zwei verschiedene Nachrichten** für jede gesendete Message:

#### **1. An Sender (Echo/Bestätigung):**
```json
{
  "type": "message",
  "role": "sender_confirmation",
  "text": "Original-Text",
  "audio_available": false,
  "sender": "admin"
}
```

**Frontend-Empfehlung:** Kann ignoriert werden wenn optimistische UI-Updates verwendet werden (Frontend zeigt eigene Nachrichten bereits lokal an).

#### **2. An Empfänger (Übersetzung + Audio):**
```json
{
  "type": "message",
  "role": "receiver_message",
  "text": "Übersetzter Text",
  "audio_available": true,
  "audio_url": "/api/audio/xxx.wav",
  "sender": "admin"
}
```

**Frontend-Empfehlung:** **MUSS** angezeigt werden. Enthält die übersetzte Nachricht für den anderen Client.

> **Wichtig:** Das `sender`-Feld identifiziert immer den **ursprünglichen Absender** der Nachricht, nicht den Empfänger. Verwende `role` um zu unterscheiden ob es sich um ein Echo (`sender_confirmation`) oder eine neue Nachricht (`receiver_message`) handelt.

**Detaillierte Dokumentation:** Siehe `/docs/WEBSOCKET_MESSAGE_ROLES.md`
```

- Spezialnachrichten `session_terminated` informieren über ein Gesprächsende.
- Optional: `GET /api/websocket/stats` stellt Monitoring-Infos bereit.

## 6. WebSocket-Troubleshooting

### 6.1 Verbindungsdiagnose

Für WebSocket-Probleme steht ein Diagnose-Endpunkt zur Verfügung:

```javascript
// WebSocket-Kompatibilität prüfen
fetch('/api/websocket/debug/connection-test', {
  method: 'GET',
  headers: {
    'Content-Type': 'application/json'
  }
})
.then(response => response.json())
.then(data => {
  console.log('WebSocket-Diagnose:', data);
  if (data.origin_allowed) {
    console.log('✅ Origin erlaubt - WebSocket sollte funktionieren');
  } else {
    console.log('❌ Origin blockiert:', data.suggestions);
  }
});
```

### 6.2 Automatischer Fallback

Bei WebSocket-Problemen aktiviert das System automatisch Polling-Fallback:

1. **WebSocket-Verbindung schlägt fehl** → System erkennt Problem automatisch
2. **Fallback-Nachricht erhalten:**
   ```json
   {
     "type": "fallback_activated",
     "polling_id": "...",
     "polling_endpoint": "/api/websocket/poll/...",
     "instructions": {
       "action": "switch_to_polling",
       "polling_interval": 5
     }
   }
   ```
3. **Client wechselt zu Polling:** Verwende den bereitgestellten `polling_endpoint`

### 6.3 Häufige WebSocket-Probleme

| Problem | Symptom | Lösung |
|---------|---------|--------|
| **CORS-Blockierung** | "Origin not allowed" | Figma-Domains (*.figma.site) sind automatisch erlaubt |
| **"Failed to fetch"** | Preflight-Request schlägt fehl | System aktiviert automatisch Polling-Fallback |
| **Connection Timeout** | WebSocket öffnet nicht | Prüfe Netzwerk/Firewall, System aktiviert Fallback |
| **Unexpected close** | Verbindung bricht ab | Überprüfe Session-Status, System versucht Reconnect |

### 6.4 Client-Implementierung mit Fallback

```javascript
class WebSocketClient {
  constructor(sessionId, clientType) {
    this.sessionId = sessionId;
    this.clientType = clientType;
    this.pollingId = null;
    this.pollingInterval = null;
  }

  async connect() {
    try {
      // WebSocket versuchen
      const wsUrl = `wss://ssf.smart-village.solutions/ws/${this.sessionId}/${this.clientType}`;
      this.ws = new WebSocket(wsUrl);

      this.ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'fallback_activated') {
          this.activateFallback(data.polling_id);
        } else {
          this.onMessage(data);
        }
      };

      this.ws.onerror = () => {
        console.log('WebSocket failed, fallback will be activated automatically');
      };

    } catch (error) {
      console.log('WebSocket connection failed:', error);
      // Fallback wird automatisch aktiviert
    }
  }

  activateFallback(pollingId) {
    this.pollingId = pollingId;
    this.startPolling();
  }

  startPolling() {
    this.pollingInterval = setInterval(async () => {
      try {
        const response = await fetch(`/api/websocket/poll/${this.pollingId}`);
        const data = await response.json();
        if (data.messages) {
          data.messages.forEach(msg => this.onMessage(msg));
        }
      } catch (error) {
        console.error('Polling failed:', error);
      }
    }, 5000);
  }

  onMessage(data) {
    // Verarbeite Nachrichten (identisch für WebSocket und Polling)
    console.log('Message received:', data);
  }
}
```

## 7. Fehlerrückgaben

- Ungültige Session: `404` mit `detail`-Payload.
- Fehlende Felder: `400` mit `error_code` und `details`. Beispiel bei Multipart: `"MISSING_FIELDS"`.
- Audiofehler (z. B. nicht unterstütztes Format): `400` mit `AUDIO_VALIDATION_FAILED`.
- Allgemeine Fehler: `500` mit `PROCESSING_ERROR`.

Das Frontend sollte Fehlermeldungen aus `detail` anzeigen und Nutzer*innen entsprechend informieren (z. B. Session nicht verfügbar, Audio zu kurz/lang, Sprache nicht unterstützt).

---

## 8. Pipeline Metadata (NEU)

**Verfügbar ab:** Version 2.0 (November 2025)
**Status:** Prototyp-Phase - immer verfügbar in allen Nachrichten

### 8.1 Überblick

Alle Nachrichten (HTTP-Responses und WebSocket-Messages) enthalten jetzt ein `pipeline_metadata`-Feld mit detaillierten Informationen über jeden Verarbeitungsschritt:

- **ASR** (Automatic Speech Recognition) - nur bei Audio-Input
- **Translation** (Übersetzung)
- **Refinement** (LLM-basierte Verbesserung) - optional, wenn aktiviert
- **TTS** (Text-to-Speech)

### 8.2 Struktur

```typescript
interface PipelineMetadata {
  input: {
    type: "audio" | "text";
    source_lang: string;
    audio_url?: string;  // Nur bei Audio-Input, 24h gültig
  };
  steps: PipelineStep[];
  total_duration_ms: number;
  pipeline_started_at: string;  // ISO 8601 UTC
  pipeline_completed_at: string;  // ISO 8601 UTC
}

interface PipelineStep {
  name: "asr" | "translation" | "refinement" | "tts";
  started_at: string;  // ISO 8601 UTC, z.B. "2025-11-02T11:32:05.100Z"
  completed_at: string;  // ISO 8601 UTC
  duration_ms: number;  // Dauer in Millisekunden
  input: Record<string, any>;  // Step-spezifische Eingabe
  output: Record<string, any>;  // Step-spezifische Ausgabe
}
```

### 8.3 Verwendungsbeispiele

#### **Performance-Monitoring**

```typescript
function analyzePerformance(metadata: PipelineMetadata) {
  const slowSteps = metadata.steps.filter(step => step.duration_ms > 1000);

  if (slowSteps.length > 0) {
    console.warn('Langsame Pipeline-Schritte:', slowSteps.map(s => s.name));
  }

  // Gesamt-Performance anzeigen
  console.log(`Pipeline-Dauer: ${metadata.total_duration_ms}ms`);

  // Pro-Step Breakdown
  metadata.steps.forEach(step => {
    const percentage = (step.duration_ms / metadata.total_duration_ms * 100).toFixed(1);
    console.log(`${step.name}: ${step.duration_ms}ms (${percentage}%)`);
  });
}
```

#### **Original-Audio Zugriff**

```typescript
function getOriginalAudio(metadata: PipelineMetadata): string | null {
  if (metadata.input.type === 'audio' && metadata.input.audio_url) {
    return metadata.input.audio_url;
  }
  return null;
}

// Verwendung
const originalUrl = getOriginalAudio(message.pipeline_metadata);
if (originalUrl) {
  // Zeige "Original anhören" Button
  audioPlayer.src = `https://ssf.smart-village.solutions${originalUrl}`;
}
```

#### **Debugging fehlgeschlagener Übersetzungen**

```typescript
function debugTranslation(metadata: PipelineMetadata) {
  const translationStep = metadata.steps.find(s => s.name === 'translation');

  if (translationStep) {
    console.log('Übersetzungs-Input:', translationStep.input.text);
    console.log('Übersetzungs-Output:', translationStep.output.text);
    console.log('Verwendetes Modell:', translationStep.output.model);
    console.log('Dauer:', translationStep.duration_ms, 'ms');
  }
}
```

### 8.4 Retention Policy für Original-Audio

**Wichtig:** Original-Audiodateien werden aus Datenschutzgründen **nach 24 Stunden automatisch gelöscht**.

- URLs in `pipeline_metadata.input.audio_url` sind nur 24h gültig
- Nach Ablauf gibt `GET /api/audio/input_{message_id}.wav` → `404 Not Found`
- Frontend sollte dies behandeln und ggf. Hinweis anzeigen:

```typescript
async function playOriginalAudio(url: string) {
  try {
    const response = await fetch(url);
    if (response.status === 404) {
      showNotification('Original-Audio wurde nach 24h gelöscht (Datenschutz)');
      return;
    }
    const blob = await response.blob();
    audioPlayer.src = URL.createObjectURL(blob);
    audioPlayer.play();
  } catch (error) {
    console.error('Fehler beim Laden des Originals:', error);
  }
}
```

### 8.5 Backward Compatibility

**Garantiert:** Alte Frontend-Versionen funktionieren weiterhin einwandfrei.

- `pipeline_metadata` ist ein **zusätzliches** Feld
- Alle bestehenden Felder bleiben unverändert
- Alte Clients können `pipeline_metadata` einfach ignorieren

### 8.6 Monitoring-Metriken

Das Backend exportiert Prometheus-Metriken für Audio-Storage:

- `audio_storage_disk_usage_bytes{directory="original|translated"}` - Disk-Nutzung in Bytes
- `audio_files_total{directory="original|translated"}` - Anzahl gespeicherter Dateien
- `audio_cleanup_deleted_files_total{directory="original|translated"}` - Gelöschte Dateien durch Cleanup

DevOps-Teams können diese Metriken für Alerting verwenden (z.B. Warnung bei >80% Disk-Nutzung).
