# Smart Speech Flow Frontend

## Deployment display name

Set `app.name` in every `src/i18n/locales/*.json` catalogue for the deployment.
Customer and staff copy, accessible logo names, and the browser title use this
value. The initial HTML title is taken from `de.json` when Vite builds the app.
The Kassel deployment uses `KasselDIALOG`. The gateway uses `SSF_DISPLAY_NAME`
for its landing page and API title; set it to the same name on another server.
For a different visual brand, build the frontend image with
`--build-arg VITE_BRAND=ssf`; its header displays the catalogue name as text.

## Beschreibung

Das Frontend ist eine React-, TypeScript- und Vite-Anwendung fuer die sessionbasierte Nutzung von Smart Speech Flow.

Es stellt drei zentrale Nutzungspfade bereit:

- a start page where customers enter their session code
- a staff interface behind the tenant Keycloak login for creating and running conversations
- a customer interface for QR links, language choice and messaging

## Kernfunktionen

- Session-Erstellung fuer Admins
- Deeplink-basierter Session-Beitritt fuer Customers
- Text- und Audioeingaben
- WebSocket-basierte Echtzeitkommunikation
- Nachrichtenhistorie und Audio-Wiedergabe
- responsive Nutzung auf Desktop und Mobilgeraeten

## Routen

- `/` - session code entry for customers
- `/join/:sessionId` - QR and link entry, straight to the language choice
- `/s/:sessionId/language`, `/s/:sessionId/info/:languageCode`, `/s/:sessionId/live` - customer language choice, information and conversation
- `/login` - organisation chooser for staff
- `/login/:tenantId` - Keycloak login and staff dashboard for one organisation

## Studio administration navigation

The authenticated tenant menu shows **Organisation verwalten** only when the
current Keycloak access token contains `ssf.configuration.tenant.manage` in its
`ssf_permissions` array and `studio_tenant_id` matches the selected tenant.
Realm roles (including `system_admin`) and configuration read access do not
satisfy this check. The link uses only `studioUrl` from the validated public
tenant directory; missing destinations produce no link and invalid entries are
rejected by the existing directory mapper. No credentials are added to the URL.
Token refresh and tenant/session changes re-evaluate visibility. This navigation
hint does not grant conversation permissions or replace Studio authorization.

## API-Bezug

Das Frontend spricht gegen das API Gateway und nutzt insbesondere:

- `POST /api/admin/session/create`
- `POST /api/customer/session/activate`
- `GET /api/languages/supported`
- `POST /api/session/{sessionId}/message`
- `GET /api/session/{sessionId}/messages`
- `WS /ws/{sessionId}/{clientType}`

## Konfiguration

Die wichtigsten Umgebungsvariablen sind:

```env
VITE_API_BASE_URL=https://ssf.smart-village.solutions
VITE_WS_BASE_URL=wss://ssf.smart-village.solutions
```

Im Docker-Betrieb werden diese Werte ueber `docker-compose.yml` gesetzt.

## Lokale Entwicklung

```bash
cd services/frontend
npm install
npm run dev
```

Standardmaessig laeuft Vite lokal auf `http://localhost:5173` oder dem naechsten freien Port.

## Build

```bash
cd services/frontend
npm run build
```

## Deployment

Im Projekt wird das Frontend als eigener Container mit Nginx betrieben:

```bash
docker compose build frontend
docker compose up -d frontend
```

Der produktive Einstiegspunkt ist:

- `https://translate.smart-village.solutions`

## Wichtige Quellbereiche

- `src/pages/` - Seiten fuer Landing, Admin, Customer und Not Found
- `src/components/` - UI-Komponenten
- `src/contexts/` - Session- und Toast-Context
- `src/services/` - API- und WebSocket-Anbindung
- `src/utils/` - Audio-bezogene Hilfslogik

## Hinweise

- Fuer die Customer-Reise ist die Aktivierung ueber `POST /api/customer/session/activate` ein notwendiger Schritt vor dem Nachrichtenaustausch.
- Die Frontend-Domain und die API-/WebSocket-Basis-URLs sollten in Deployment und lokaler Entwicklung konsistent gesetzt sein.
