# WebSocket Architecture

## Overview

This document describes how the API gateway delivers conversation messages in
real time: the WebSocket endpoints, the collaborators behind them, the polling
fallback that receives the same broadcasts, and how each app owns its own
realtime state.

The public behaviour is pinned by `tests/gateway_contract/`:
`test_contract_websocket.py`, `test_contract_realtime_frames.py`,
`test_contract_heartbeat.py`, `test_contract_message_delivery.py`,
`test_contract_polling.py`, `test_contract_realtime_tickets.py`,
`test_contract_realtime_isolation.py` and `test_contract_realtime_metrics.py`.

## Ownership

Each gateway app owns one `WebSocketManager`. `build_gateway_dependencies`
(`services/api_gateway/dependencies.py`) builds it in the app's lifespan with
that app's `TenantSessionManager`, `TenantPollingStore` and `WebSocketMonitor`,
and keeps it in the app's `GatewayDependencies`. The endpoints, the polling
routes and `ConversationService` reach it through `get_websocket_manager` or by
constructor; nothing holds a module-level manager. Two apps in one process share
no socket, poller, monitor or metric (`tests/test_gateway_app_isolation.py`).

```
lifespan ── build_gateway_dependencies
               ├─ TenantSessionManager ◄──────────────┐ SessionRegistry / SessionSockets
               ├─ TenantPollingStore                  │
               ├─ WebSocketMonitor ── WebSocketMetrics (the app's registry)
               ├─ WebSocketManager (facade) ──────────┘
               │     ├─ ConnectionRegistry
               │     ├─ BroadcastDispatcher ── TenantPollingStore
               │     ├─ Heartbeat
               │     └─ ClientStatusHandler ── AdaptivePollingManager
               └─ ConversationService ── WebSocketManager
```

## Collaborators

`WebSocketManager` (`websocket.py`) is a facade. It keeps the socket lifecycle
(connect, disconnect, session termination) and the dispatch of inbound frames,
and builds four collaborators, each given its dependencies by constructor:

| Collaborator | Module | Owns |
| --- | --- | --- |
| `ConnectionRegistry` | `realtime_registry.py` | the session pools keyed by `TenantSessionKey`, the app-wide connection map, connection ids and lookup |
| `BroadcastDispatcher` | `realtime_dispatch.py` | `broadcast_to_session`, the differentiated broadcast, delivery to the session's pollers, the broadcast metrics |
| `Heartbeat` | `realtime_heartbeat.py` | the heartbeat task, pings, pong latency and closing a silent socket |
| `ClientStatusHandler` | `realtime_client_status.py` | the tab, battery and network reports and the adaptive polling interval |

`WebSocketConnection` and the time helpers live in `realtime_connection.py`.
`realtime_protocol.py` holds `MessageType`, `ConnectionState` and one builder
per server frame; `tests/test_realtime_protocol_guard.py` fails when another
gateway module writes a frame inline.

The session manager and the WebSocket manager meet through two protocols in
`session_manager.py`: the manager reads sessions as a
`SessionRegistry[TenantSessionKey]`, and the session manager terminates and
broadcasts through the manager as a `SessionSockets[TenantSessionKey]`.

## Endpoints and connection lifecycle

- `WS /ws/admin/{session_id}?ticket=...`: the admin first gets a single-use
  ticket from `POST /api/admin/session/{session_id}/realtime-ticket`. The
  endpoint consumes it through the app's `RealtimeTicketStore`; an unavailable
  ticket store closes with 1013, and an unknown ticket or a lapsed session with
  4404.
- `WS /ws/customer/{session_id}`: the customer's session key comes from
  `require_customer_session_key`, the same guard the customer REST routes use.

Both then check the `Origin` header (1008 if it is not allowed) and the
session (1003 if it is missing or terminated), and register the socket. The
client receives `connection_ack` with the heartbeat interval; its peers receive
`client_joined`. Inbound `message` and `typing_indicator` frames are relayed to
the session's other sockets and pollers, never back to the sender. A frame
that is not a JSON object is answered with `error`, and the socket stays open.

On disconnect the socket is released, its peers receive `client_left` with the
reason, and the monitor records the disconnect. When the session ends, every
socket receives `session_terminated` and is closed with 1000; the session
manager also revokes the session's realtime tickets and notifies its pollers.

## Message delivery

A message posted to `POST /api/{admin|customer}/session/{session_id}/message`
goes through `ConversationService`, which runs the pipeline and then calls the
differentiated broadcast: the sender's sockets receive a sender confirmation
with the original text, and the receiver's sockets and pollers receive the
translated text, the audio URLs and the pipeline metadata scoped to their role.

## Heartbeat

The heartbeat task starts with the app's first socket and pings every
connection every 30 seconds. A pong, with or without the ping's `ping_id`,
marks the connection healthy; an echoed `ping_id` is timed for
`websocket_heartbeat_latency_seconds`. A connection that sends no pong for 60
seconds gets a `connection_status` frame (`disconnecting`,
`heartbeat_timeout`) and is closed with 1001, and its peers receive
`client_left`. The lifespan stops the task at shutdown.

## Polling fallback

A client that cannot keep a WebSocket open activates a poller below
`/api/{admin|customer}/session/{session_id}/polling`. `TenantPollingStore`
(`websocket_polling_routes.py`) keeps a bounded queue per poller, at most ten
pollers per role and session, and counts dropped messages in
`tenant_polling_messages_dropped_total`. `BroadcastDispatcher` delivers every
broadcast to the session's pollers as well as its sockets, and a message sent
through a poller reaches the other role's sockets and pollers.

## Tenant isolation

Every pool, poller and ticket is keyed by `TenantSessionKey`, so two tenants'
sessions with the same id never share a connection or a frame. A ticket is
bound to its tenant, session and transport. `test_contract_realtime_isolation.py`
and `tests/integration/test_tenant_isolation_matrix.py` cover the cross-tenant
denials.

## Monitoring

`WebSocketMonitor` (`websocket_monitor.py`) keeps the app's connection records,
history and session index, and serves `GET /api/websocket/monitoring/health`.
It counts into the app's `WebSocketMetrics`, on the registry `/metrics` serves:
`websocket_connections_total`, `websocket_connections_active`,
`websocket_disconnects_total`, `websocket_connection_duration_seconds`,
`websocket_messages_sent_total`, `websocket_messages_received_total`,
`websocket_message_size_bytes`, `websocket_errors_total`,
`websocket_heartbeat_latency_seconds`, `websocket_sessions_with_connections`,
`websocket_connections_per_session`, the broadcast counters,
`websocket_monitor_initialized` and `websocket_system_info`. #348 decides the
public, tenant-scoped monitoring surface.

## Troubleshooting

- **A message reaches no one:** a broadcast to a session with no open socket or
  poller reports failure and logs `WebSocket-Broadcasting fehlgeschlagen` with
  its send counts. Check that the receiver's socket was accepted
  (`connection_ack`) and has not been closed by the heartbeat.
- **Sockets close with `heartbeat_timeout`:** the client is not answering
  `heartbeat_ping` with `heartbeat_pong`.
- **The admin socket closes with 4404:** the ticket was already used, expired
  after 60 seconds, belongs to another session, or the session has ended.
- **Sockets close with 1008 `Origin not allowed`:** the frontend's origin is
  not among the configured client origins.
