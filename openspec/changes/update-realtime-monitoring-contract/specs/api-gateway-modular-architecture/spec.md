## MODIFIED Requirements

### Requirement: Focused realtime collaboration

The gateway SHALL express realtime ticket consumption, registry ownership, dispatch, heartbeat, polling fallback, and monitoring through focused interfaces that do not expose Redis wire details to application code.

Realtime connection metadata SHALL be served only by `GET /api/admin/realtime/connections` and `GET /api/admin/session/{session_id}/realtime/connections`, which require a signed tenant bearer token and serve only connections of the requesting admin's own sessions in the signed tenant. `GET /api/websocket/monitoring/health` SHALL be the only route below `/api/websocket/monitoring`; it SHALL require no authentication and SHALL report only aggregate counts. Prometheus WebSocket metrics SHALL carry no tenant or session label.

#### Scenario: Single-use realtime ticket

- **WHEN** a realtime ticket is consumed
- **THEN** the ticket backend performs a single domain consume operation and the memory and Redis implementations preserve the same single-use result

#### Scenario: Tenant-safe monitoring

- **WHEN** an authenticated caller requests supported realtime connection information
- **THEN** the route applies tenant authorization and does not disclose another tenant's connection metadata

#### Scenario: Permitted session connection listing

- **WHEN** an admin requests the realtime connections of a session they own while a client is connected
- **THEN** the gateway lists that connection with its transport and client type

#### Scenario: A colleague's session connections

- **WHEN** an admin requests the realtime connections of a session another admin of the same tenant owns
- **THEN** the gateway answers `404 Session not found` and the tenant listing omits that session's connections

#### Scenario: Unauthenticated connection listing

- **WHEN** a caller without a bearer token requests either realtime connection listing
- **THEN** the gateway answers `401` and discloses no connection

#### Scenario: Aggregate-only public health

- **WHEN** any caller requests `GET /api/websocket/monitoring/health` while clients of several tenants are connected
- **THEN** the response contains only `status`, `active_connections`, `healthy_connections`, `stale_connections`, `sessions_with_connections`, `monitoring_active` and `last_check`, and no session, tenant, connection or client identifier

#### Scenario: No global connection listing

- **WHEN** a caller requests `/api/websocket/monitoring/stats` or `/api/websocket/monitoring/connections`
- **THEN** the gateway answers `404`
