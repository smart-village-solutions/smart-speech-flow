# Change: Tenant-safe WebSocket monitoring contract

## Why

Before the tenant-isolation migration the gateway served global, unauthenticated
WebSocket monitoring endpoints at `/api/websocket/monitoring/stats` and
`/api/websocket/monitoring/connections`. They are no longer registered, but
nothing records which monitoring surface is supported, the gateway still carries
a helper that breaks connections down per session across every tenant, and the
legacy integration helper still calls the removed endpoints (#348).

## What Changes

- Record the supported realtime monitoring surface:
  - `GET /api/admin/realtime/connections` and
    `GET /api/admin/session/{session_id}/realtime/connections` are the only
    sources of connection metadata. They require a signed tenant bearer token and
    serve only the requesting admin's own sessions (unchanged, #476).
  - `GET /api/websocket/monitoring/health` stays public and unauthenticated, as
    decided on 2026-09-30. It reports aggregate counts across the instance and no
    session, tenant, connection or client identifier.
  - Prometheus WebSocket metrics on `/metrics` carry no tenant or session label.
  - No global connection listing or statistics endpoint exists.
- Remove `WebSocketMonitor.get_connection_stats()` and the connection history only
  it read. No route used it, and it grouped connections by session across tenants.
  The unused `_performance_samples` and `_extract_domain` go with it.
- Remove `tests/integration/test_websocket_integration.py`. It collected no tests
  and drove only retired routes (`/api/session/create`,
  `/api/websocket/polling/*`, `/api/websocket/monitoring/stats` and
  `/connections`). The contract suite covers the supported realtime flows.
- Contract tests pin the monitoring route table, the health payload's aggregate
  fields, and permitted and cross-tenant access to the session connection listing.

No route, response or authorization changes.

## Impact

- Affected specs: `api-gateway-modular-architecture`
- Affected code: `services/api_gateway/websocket_monitor.py`; tests in
  `tests/gateway_contract/`, `tests/test_tenant_websocket.py`,
  `tests/test_websocket_polling_coverage.py`; removal of
  `tests/integration/test_websocket_integration.py`
- Affected docs: `docs/architecture/websocket-architecture.md`,
  `services/api_gateway/README.md`, `docs/testing/TESTING_GUIDE.md`
- Issue: #348
