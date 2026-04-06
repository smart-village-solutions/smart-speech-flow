# Smart Speech Flow Frontend

## Beschreibung

Das Frontend ist eine React-, TypeScript- und Vite-Anwendung fuer die sessionbasierte Nutzung von Smart Speech Flow.

Es stellt drei zentrale Nutzungspfade bereit:

- passwortgeschuetzte Landingpage
- Admin-Oberflaeche fuer Session-Erstellung und Gespraechsfuehrung
- Customer-Oberflaeche fuer Deeplinks, Sprachwahl und Nachrichtenversand

## Kernfunktionen

- Session-Erstellung fuer Admins
- Deeplink-basierter Session-Beitritt fuer Customers
- Text- und Audioeingaben
- WebSocket-basierte Echtzeitkommunikation
- Nachrichtenhistorie und Audio-Wiedergabe
- responsive Nutzung auf Desktop und Mobilgeraeten

## Routen

- `/` - Landingpage
- `/admin` - Admin-Bereich
- `/customer` - Customer-Bereich
- `/join/:sessionId` - Deeplink fuer Customer-Session-Beitritt

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
VITE_APP_PASSWORD=<demo-password>
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

- Die Anwendung ist auf die sessionbasierte API abgestimmt, nicht auf direkte Nutzung von `/pipeline`.
- Fuer die Customer-Reise ist die Aktivierung ueber `POST /api/customer/session/activate` ein notwendiger Schritt vor dem Nachrichtenaustausch.
- Die Frontend-Domain und die API-/WebSocket-Basis-URLs sollten in Deployment und lokaler Entwicklung konsistent gesetzt sein.
