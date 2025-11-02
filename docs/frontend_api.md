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
   - Kund*innen wählen ihre Sprache (`source_lang`) sowie optional die gewünschte Zielsprache (`target_lang`).

> **Hinweis:** Die Session bleibt in `pending`, bis eine Nachricht gesendet wurde. Die gewählten Sprachen werden bei jeder Nachricht im jeweiligen Request angegeben und so an die Pipeline übergeben.

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

- Pflichtfelder: `text`, `source_lang`, `target_lang`, `client_type` (`admin` oder `customer`).
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
  "timestamp": "2025-11-02T11:32:05.418216"
}
```

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

## 4. Antworten konsumieren

### 4.1 Audio abrufen

- Wenn `audio_available` true ist, kann der Browser die Datei über
  `GET /api/audio/{message_id}.wav`
  abspielen oder herunterladen.

### 4.2 Verlauf & Status aktualisieren

- `GET /api/session/{sessionId}/messages` liefert die komplette Nachrichtenliste (`original_text`, `translated_text`, `audio_base64`, `timestamp`).
- `GET /api/session/{sessionId}` kann für regelmäßige Statusprüfungen (z. B. Session beendet) genutzt werden.

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

- Verbindungs-URL: `wss://translate.smart-village.solutions/ws/{sessionId}/{clientType}`
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
  "role": "receiver_message"
}
```

- Spezialnachrichten `session_terminated` informieren über ein Gesprächsende.
- Optional: `GET /api/websocket/stats` stellt Monitoring-Infos bereit.

## 6. Fehlerrückgaben

- Ungültige Session: `404` mit `detail`-Payload.
- Fehlende Felder: `400` mit `error_code` und `details`. Beispiel bei Multipart: `"MISSING_FIELDS"`.
- Audiofehler (z. B. nicht unterstütztes Format): `400` mit `AUDIO_VALIDATION_FAILED`.
- Allgemeine Fehler: `500` mit `PROCESSING_ERROR`.

Das Frontend sollte Fehlermeldungen aus `detail` anzeigen und Nutzer*innen entsprechend informieren (z. B. Session nicht verfügbar, Audio zu kurz/lang, Sprache nicht unterstützt).
