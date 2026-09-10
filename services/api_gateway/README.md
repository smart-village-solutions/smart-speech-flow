# API Gateway Service

## Studio-backed login directory

`GET /api/login/tenants` is an anonymous, read-only facade over Studio's
validated login directory. Studio is the source of truth for ready tenant
realms. The gateway uses one trusted `KEYCLOAK_BASE_URL`, admits only issuers
derived from current directory entries, and binds a validated token to its
signed `studio_tenant_id` and `ssf_authorization_revision` claims.

Production requires these settings:

```text
KEYCLOAK_BASE_URL=https://auth.dialog.kassel.de
KEYCLOAK_AUDIENCE=ssf-frontend
KEYCLOAK_REQUIRED_ROLE=ssf-user
STUDIO_RUNTIME_CONFIGURATION_BASE_URL=https://studio.dialog.kassel.de
STUDIO_RUNTIME_TOKEN_URL=<OAuth2 token endpoint>
STUDIO_RUNTIME_CLIENT_ID=ssf-runtime
STUDIO_RUNTIME_AUDIENCE=sva-studio-ssf-runtime
STUDIO_RUNTIME_CLIENT_SECRET=<deployment secret>
STUDIO_LOGIN_DIRECTORY_CACHE_SECONDS=60
```

The client secret must come from the deployment environment or secret store;
it must never be embedded in an image, browser bundle, or checked-in file.
Production Compose intentionally does not import the fixed local `ssf` realm.
Studio owns production realm provisioning.

## Multi-tenant rollout gate

Directory-based login establishes a trusted tenant identity, but it does not
make conversation persistence tenant-isolated. Before exposing real
conversations through multi-realm login, operators must complete all of the
following:

1. Confirm the Studio directory returns at least two ready tenant entries.
2. Confirm every listed realm has the common public client, PKCE S256, the
   exact application origin and `/login/*` redirects, the configured audience
   and role, and signed tenant-ID and authorization-revision claims.
3. Set `SSF_ENABLE_LEGACY_ADMIN_ACCESS=false` before multi-realm production
   enablement.
4. Complete the separate OpenSpec change `add-multi-tenant-operations` and pass
   its isolation tests for session creation, history, lookup, termination,
   messages, audio, and customer joins. This is an independent release gate,
   not part of the tenant-login-directory implementation.
5. Manually verify login, existing SSO, logout, unknown-tenant handling, a
   Studio outage after cache expiry, and cross-tenant negative paths in the
   deployed environment.

If any gate is incomplete, keep real multi-tenant conversations disabled. A
healthy directory or successful login alone is not production approval.

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
