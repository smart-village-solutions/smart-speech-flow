# API Gateway Service

## Beschreibung

Das API Gateway ist der zentrale Einstiegspunkt fuer Smart Speech Flow. Es verbindet die Fachservices fuer ASR, Translation und TTS mit der sessionbasierten Admin/Customer-Kommunikation im Frontend.

Heute ist das Gateway nicht nur ein einfacher Pipeline-Proxy, sondern vor allem:

- Session-Manager fuer Admin- und Customer-Gespraeche
- Unified Message API fuer Text und Audio
- WebSocket-Hub fuer Echtzeitkommunikation
- Persistenz- und Timeout-Schicht fuer Sessions
- Fallback- und Monitoring-Schicht fuer produktionsnahe Nutzung

## Primaere API-Oberflaeche

Der empfohlene Einstieg fuer Frontends laeuft ueber die sessionbasierten Endpunkte:

- `POST /api/admin/session/create`
- `GET /api/admin/session/current`
- `POST /api/customer/session/activate`
- `GET /api/customer/session/{session_id}/status`
- `POST /api/session/{session_id}/message`
- `GET /api/session/{session_id}/messages`
- `GET /api/languages/supported`
- `WS /ws/{session_id}/{client_type}`

## Legacy- und Low-Level-Endpunkte

Zusaetzlich existieren weiterhin generische Gateway-Endpunkte:

- `POST /pipeline`
- `POST /upload`
- `GET /health`
- `GET /metrics`
- `GET /languages`

`/pipeline` ist weiterhin nuetzlich fuer direkte End-to-End-Tests, bildet aber nicht den heutigen Haupt-Workflow des Frontends ab.

## Typischer Frontend-Workflow

1. Admin erstellt eine Session ueber `POST /api/admin/session/create`
2. Customer waehlt Sprache und aktiviert die Session ueber `POST /api/customer/session/activate`
3. Beide Seiten verbinden sich per WebSocket an `/ws/{session_id}/{client_type}`
4. Nachrichten laufen ueber `POST /api/session/{session_id}/message`
5. Historie und Audio koennen ueber REST-Endpunkte nachgeladen werden

## Unified Message Endpoint

### `POST /api/session/{session_id}/message`

Der Endpoint akzeptiert beide Eingabeformen:

- `application/json` fuer Textnachrichten
- `multipart/form-data` fuer Audioeingaben

### Text-Beispiel

```json
{
  "text": "Guten Tag",
  "source_lang": "de",
  "target_lang": "en",
  "client_type": "admin"
}
```

### Audio-Beispiel

Multipart-Request mit:

- `file`
- `source_lang`
- `target_lang`
- `client_type`

### Response

Der Endpoint liefert ein einheitliches Response-Schema mit:

- `status`
- `message_id`
- `session_id`
- `original_text`
- `translated_text`
- `audio_available`
- `audio_url`
- `processing_time_ms`
- `pipeline_type`
- `pipeline_metadata`

## Weitere wichtige Endpunkte

### `GET /api/session/{session_id}/messages`

Liefert die Nachrichtenhistorie einer Session.

### `GET /api/audio/{message_id}.wav`

Liefert das erzeugte Audio einer Nachricht.

### `GET /api/audio/input_{message_id}.wav`

Liefert das urspruengliche Eingabe-Audio, sofern es noch innerhalb der Aufbewahrungszeit vorhanden ist.

### `GET /api/languages/supported`

Liefert die vom Frontend verwendete Sprachliste inklusive `admin_default` und `popular`.

### `GET /languages`

Oeffentlicher Alias fuer die Sprachliste ohne `/api`-Praefix.

## Betrieb und Architektur

Das Gateway umfasst unter anderem:

- Session-Management mit optionaler Redis-Persistenz
- WebSocket-Management mit Heartbeats
- Polling-Fallback bei Verbindungsproblemen
- Audio-Validierung und Text-Validierung
- Circuit Breaker und Graceful Degradation
- Monitoring ueber Prometheus-Metriken

## Lokale Entwicklung

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn services.api_gateway.app:app --reload --port 8000
```

## Docker

Der Service wird im Projektkontext ueber das Root-`docker-compose.yml` gestartet:

```bash
docker compose up -d api_gateway
```

## Testen

```bash
pytest services/api_gateway/tests/
pytest tests/test_unified_message_endpoint.py
pytest tests/test_websocket_manager.py
```

## Hinweise

- Fuer neue Frontend-Integrationen sollte immer die sessionbasierte API verwendet werden.
- `/pipeline` bleibt fuer direkte Service-Tests und technische Integrationen sinnvoll, ist aber nicht mehr die alleinige Leit-API.
